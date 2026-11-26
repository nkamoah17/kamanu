//! The one-shot allocator (Linux): a lint run is one short process, so its heap is one region mapped once and
//! pre-faulted in one call, handed out by bumping a pointer; freeing gives memory back only when it is the
//! last block (the rest is returned with the process). This trades nothing the run can see for the page
//! faults and bookkeeping of a general allocator, which were most of a cold run's time beyond exec. Past
//! the region, and for the bulk modes (which switch it off before they start threads), the system
//! allocator serves as before.

use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering::Relaxed};

/// The region's size (address space only), and how much of it is pre-faulted at the first allocation.
const SIZE: usize = 4 << 20;
const WARM: usize = 192 << 10;

static BASE: AtomicUsize = AtomicUsize::new(0); // 0: not mapped yet; usize::MAX: mapping failed
static NEXT: AtomicUsize = AtomicUsize::new(0);
static ON: AtomicBool = AtomicBool::new(true);
static HIGH: AtomicUsize = AtomicUsize::new(0);

extern "C" {
    fn mmap(addr: *mut u8, len: usize, prot: i32, flags: i32, fd: i32, off: i64) -> *mut u8;
    fn madvise(addr: *mut u8, len: usize, advice: i32) -> i32;
}
const PROT_READ: i32 = 1;
const PROT_WRITE: i32 = 2;
const MAP_PRIVATE: i32 = 0x02;
const MAP_ANONYMOUS: i32 = 0x20;
const MAP_NORESERVE: i32 = 0x4000;
const MADV_POPULATE_WRITE: i32 = 23; // Linux 5.14; older kernels refuse it and the pages fault lazily

/// Pre-fault the next WARM bytes in one call (the lint path: a run's heap is about 170 KB).
pub fn warm() {
    unsafe {
        let b = base();
        if b != usize::MAX && ON.load(Relaxed) {
            let from = (NEXT.load(Relaxed) + 4095) & !4095;
            let len = WARM.min(b + SIZE - from);
            let _ = madvise(from as *mut u8, len, MADV_POPULATE_WRITE);
        }
    }
}

/// Switch the arena off: later allocations go to the system allocator (called before any thread starts).
pub fn off() {
    ON.store(false, Relaxed);
}

unsafe fn base() -> usize {
    let b = BASE.load(Relaxed);
    if b != 0 {
        return b;
    }
    let p = mmap(std::ptr::null_mut(), SIZE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
    let b = if p as isize == -1 || p.is_null() { usize::MAX } else { p as usize };
    BASE.store(b, Relaxed);
    NEXT.store(if b == usize::MAX { 0 } else { b }, Relaxed);
    b
}

#[inline]
fn inside(b: usize, p: *mut u8) -> bool {
    b != 0 && b != usize::MAX && (p as usize) >= b && (p as usize) < b + SIZE
}

pub struct Arena;

unsafe impl GlobalAlloc for Arena {
    #[inline]
    unsafe fn alloc(&self, l: Layout) -> *mut u8 {
        if ON.load(Relaxed) {
            let b = base();
            if b != usize::MAX {
                let start = (NEXT.load(Relaxed) + l.align() - 1) & !(l.align() - 1);
                let end = start + l.size();
                if end <= b + SIZE {
                    NEXT.store(end, Relaxed);
                    if end - b > HIGH.load(Relaxed) {
                        HIGH.store(end - b, Relaxed);
                    }
                    return start as *mut u8;
                }
            }
        }
        System.alloc(l)
    }
    #[inline]
    unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
        let b = BASE.load(Relaxed);
        if inside(b, p) {
            if ON.load(Relaxed) && p as usize + l.size() == NEXT.load(Relaxed) {
                NEXT.store(p as usize, Relaxed);
            }
            return;
        }
        System.dealloc(p, l)
    }
    #[inline]
    unsafe fn realloc(&self, p: *mut u8, l: Layout, new: usize) -> *mut u8 {
        let b = BASE.load(Relaxed);
        if inside(b, p) {
            // the last block grows (or shrinks) in place
            if ON.load(Relaxed) && p as usize + l.size() == NEXT.load(Relaxed) && p as usize + new <= b + SIZE {
                NEXT.store(p as usize + new, Relaxed);
                if p as usize + new - b > HIGH.load(Relaxed) {
                    HIGH.store(p as usize + new - b, Relaxed);
                }
                return p;
            }
            if new <= l.size() {
                return p;
            }
            let q = self.alloc(Layout::from_size_align_unchecked(new, l.align()));
            if !q.is_null() {
                std::ptr::copy_nonoverlapping(p, q, l.size());
                self.dealloc(p, l);
            }
            return q;
        }
        System.realloc(p, l, new)
    }
}

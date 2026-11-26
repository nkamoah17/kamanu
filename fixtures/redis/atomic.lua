-- kernel: S/req/R0, Atomic TRUE. The read, the comparison and the write are one script.
-- source: https://redis.io/docs/latest/develop/programmability/#running-scripts (a script runs atomically, all other clients wait)
-- source: https://redis.io/tutorials/howtos/ratelimiting/ (a limiter's read and write in one script)
-- KEYS[1] counter, ARGV[1] amount, ARGV[2] cap. Returns 1 to admit, 0 to deny.
local amount = tonumber(ARGV[1])
local cap = tonumber(ARGV[2])
local spent = tonumber(redis.call('GET', KEYS[1]) or '0')
if spent + amount > cap then
  return 0
end
redis.call('INCRBY', KEYS[1], amount)
return 1

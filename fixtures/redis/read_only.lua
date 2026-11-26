-- Atomic FALSE. A script with no write cannot hold the record: the caller writes in a later command.
-- source: https://redis.io/docs/latest/develop/programmability/#read-only-scripts
-- source: https://redis.io/docs/latest/develop/programmability/#running-scripts (atomicity is per script)
return redis.call('GET', KEYS[1])

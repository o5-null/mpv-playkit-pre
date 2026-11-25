-- mpv_filter_bench.lua
-- Frame-interpolation throughput probe, loaded by installer\mpv-FilterBench.bat.
-- Timing: from the first presented frame (playback-restart) to reaching the
-- --frames output count, so the one-off NGX/bridge initialization is excluded
-- and the number is steady-state throughput.
-- The result is printed to the terminal and appended as one TSV row to the file
-- named by MPV_BENCH_OUT.
--
-- Parameters come from environment variables (mpv normalizes "-" to "_" in
-- script names, which makes a script-opts prefix awkward):
--   MPV_BENCH_TAG    row label, e.g. VS-DLSSG-1080p
--   MPV_BENCH_OUT    TSV output file (appended)
--   MPV_BENCH_MULTI  interpolation factor, used to derive the equivalent source fps

local mp = require "mp"

local function opt(env, key)
    local v = os.getenv(env)
    if v and v ~= "" then return v end
    return mp.get_opt(key)
end

local tag   = opt("MPV_BENCH_TAG", "tag") or "run"
local out   = opt("MPV_BENCH_OUT", "out") or ""
local multi = tonumber(opt("MPV_BENCH_MULTI", "multi") or "") or 0

local t0 = nil      -- mpv time when timing started (seconds)
local w, h, src = 0, 0, 0
local done = false

-- When the clip ends before --frames is reached, derive the real output count
-- from the media position instead
local function count_frames(pos)
    local want = mp.get_property_number("options/frames") or 0
    local est = (pos and pos > 0 and src > 0 and multi > 0) and (pos * src * multi) or 0
    if want <= 0 then
        return math.floor(est + 0.5), est > 0
    end
    if est > 0 and est < want * 0.98 then
        return math.floor(est + 0.5), true     -- clip too short, use the played position
    end
    return want, false
end

local function report()
    if done or not t0 then return end
    done = true
    local elapsed = mp.get_time() - t0
    local frames, eof = count_frames(mp.get_property_number("time-pos") or 0)
    if elapsed <= 0.05 or frames <= 0 then
        print(string.format("[bench] %s aborted (elapsed=%.3fs frames=%d)", tag, elapsed, frames))
        return
    end
    local ofps = frames / elapsed
    local need = multi > 0 and ofps / multi or ofps
    local note = eof and "clip-eof" or ""
    print(string.format("[bench] %-16s %dx%d multi=%d %5d frames %6.2fs -> %7.1f out fps | %6.1f src fps %s",
        tag, w, h, multi, frames, elapsed, ofps, need, note))
    if out ~= "" then
        local f = io.open(out, "a")
        if f then
            f:write(string.format("%s\t%dx%d\t%d\t%d\t%.3f\t%.1f\t%.1f\t%s\n",
                tag, w, h, multi, frames, elapsed, ofps, need, note))
            f:close()
        end
    end
end

mp.register_event("playback-restart", function()
    if t0 then return end
    t0 = mp.get_time()
    w = mp.get_property_number("video-out-params/w") or 0
    h = mp.get_property_number("video-out-params/h") or 0
    src = mp.get_property_number("container-fps") or 0
end)

mp.register_event("end-file", function() report() end)

-- Fallback: still write a row when the run is cut short by Ctrl+C
mp.register_event("shutdown", function() report() end)

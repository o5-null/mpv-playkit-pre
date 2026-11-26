-- mpv_filter_bench.lua
-- Frame-interpolation throughput probe, loaded by installer\mpv-FilterBench.bat.
--
-- Timing: every lane needs a run-in before it reaches its real speed - NGX /
-- bridge init, model load, CUDA graph capture, and (for VFG) one CUDA lane per
-- inserted frame that warms up separately. Timing from the first presented
-- frame includes that ramp and badly understates steady-state throughput, most
-- of all for VFG. So this probe polls the presented-frame counter, waits until
-- the frame rate has settled (two adjacent windows within a tolerance), and
-- only then starts the clock. Measurement runs from that point to the end of
-- the run, or a couple of seconds after settling when the lane is slow, so a
-- stable value is what lands in the table.
--
-- The result is printed to the terminal and appended as one TSV row to the file
-- named by MPV_BENCH_OUT.
--
-- Parameters come from environment variables (mpv normalizes "-" to "_" in
-- script names, which makes a script-opts prefix awkward):
--   MPV_BENCH_TAG    row label, e.g. VS-DLSSG-1080p-2x
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

-- Warm-up / measurement tuning ------------------------------------------------
local SAMPLE_PERIOD = 0.1   -- poll interval for the presented-frame counter
local WARMUP_MIN    = 1.0   -- never call it settled earlier than this (s)
local WARMUP_MAX    = 12.0  -- give up waiting for a settled rate after this (s)
local WARM_WIN      = 1.0   -- length of each comparison window (s)
local WARM_TOL      = 0.08  -- two consecutive windows must agree within 8 %
local WARM_MIN_FRM  = 8     -- a window needs this many output frames to count
local MEASURE_MIN_S = 3.0   -- keep measuring at least this long after settling
local MEASURE_MIN_F = 60    -- ... or this many output frames, whichever is later

local t_play = nil          -- internal time when playback started
local w, h, src = 0, 0, 0
local samples = {}          -- { t = internal time, f = output frames so far }
local t0, f0 = nil, nil     -- measurement start (nil until the rate settles)
local warm = 0              -- seconds of warm-up skipped
local warm_timeout = false  -- settle check timed out, measured the rest anyway
local early_quit = false    -- stopped by MEASURE_MIN_* instead of --frames / eof
local done = false
local timer

-- Last time-pos we were told about, and when. time-pos is gone once the file is
-- unloaded, and end-file fires after that, so the final frame count has to come
-- from the observer: a live read at report time would be nil and the row would
-- silently fall back to the --frames value (which was exactly the bug that made
-- EOF runs report 3000 frames).
local frame_pos = 0
local frame_pos_t = nil

mp.observe_property("time-pos", "number", function(_, v)
    if v and v > 0 then
        frame_pos = v
        frame_pos_t = mp.get_time()
    end
end)

-- Output frames presented so far. time-pos advances with the source, so
-- pos * src * multi is the interpolated frame count. capped is true when the
-- --frames limit is what stops the run.
local function frames_now()
    local want = mp.get_property_number("options/frames") or 0
    local est  = (frame_pos > 0 and src > 0 and multi > 0) and (frame_pos * src * multi) or 0
    if want > 0 and est >= want * 0.98 then
        return want, true
    end
    return math.floor(est + 0.5), false
end

local function add_sample(t, f)
    samples[#samples + 1] = { t = t, f = f }
    -- Drop history older than the warm-up horizon; it is never compared again
    local horizon = t - (WARMUP_MAX + 2 * WARM_WIN + 2)
    while #samples > 2 and samples[1].t < horizon do
        table.remove(samples, 1)
    end
end

-- Latest sample whose time is <= t_target (nil when no sample is that old).
local function sample_at(t_target)
    for i = #samples, 1, -1 do
        if samples[i].t <= t_target then return samples[i] end
    end
    return nil
end

-- Average frame rate over [ta, tb], plus how many frames that window covered.
local function rate_between(ta, tb)
    local a, b = sample_at(ta), sample_at(tb)
    if not a or not b or b.t - a.t < SAMPLE_PERIOD * 0.75 then return nil, 0 end
    local df, dt = b.f - a.f, b.t - a.t
    if df <= 0 or dt <= 0 then return nil, 0 end
    return df / dt, df
end

-- "src_fps" is out_fps / multi, i.e. how many source frames per second the lane
-- can take at this multi. It gets a "+" when that covers the clip frame rate
-- (realtime interpolation possible) and a "-" when it does not.
local function verdict(need)
    if src > 0 then
        return need >= src and "+" or "-"
    end
    return ""
end

local function report()
    if done then return end
    done = true
    if timer then timer:stop() end

    -- Playback ended before the rate ever settled: say so explicitly instead of
    -- silently producing no row (mpv would otherwise look like a plain failure).
    if not t0 then
        local secs = t_play and (mp.get_time() - t_play) or 0
        print(string.format("[bench] %s aborted: frame rate never settled in %.1fs", tag, secs))
        if out ~= "" then
            local fh = io.open(out, "a")
            if fh then
                fh:write(string.format("%s\t%dx%d\t%d\t-\t-\t-\t-\twarmup-unfinished\n",
                    tag, w, h, multi))
                fh:close()
            end
        end
        return
    end

    -- End on the last frame we actually saw, not on the moment the event fired:
    -- file teardown adds tens of milliseconds, and at EOF time-pos is already gone.
    local t_end = (frame_pos_t and frame_pos_t > t0) and frame_pos_t or mp.get_time()
    local f_end, capped = frames_now()
    local elapsed = t_end - t0
    local frames  = f_end - f0
    if elapsed <= 0.05 or frames <= 0 then
        print(string.format("[bench] %s aborted (elapsed=%.3fs frames=%d)", tag, elapsed, frames))
        return
    end

    local ofps = frames / elapsed
    local need = multi > 0 and ofps / multi or ofps
    local mark = verdict(need)

    local notes = { string.format("warm=%.1fs", warm) }
    if warm_timeout then notes[#notes + 1] = "warm-timeout" end
    if (not capped) and (not early_quit) then notes[#notes + 1] = "clip-eof" end
    if (not early_quit) and (elapsed < MEASURE_MIN_S or frames < MEASURE_MIN_F) then
        notes[#notes + 1] = "short"
    end
    local note = table.concat(notes, ",")

    print(string.format("[bench] %-18s %dx%d multi=%d %5d frames %6.2fs -> %7.1f out fps | %6.1f src fps%s %s",
        tag, w, h, multi, frames, elapsed, ofps, need, mark, note))
    if out ~= "" then
        local fh = io.open(out, "a")
        if fh then
            fh:write(string.format("%s\t%dx%d\t%d\t%d\t%.3f\t%.1f\t%.1f%s\t%s\n",
                tag, w, h, multi, frames, elapsed, ofps, need, mark, note))
            fh:close()
        end
    end
end

-- Start the clock: from now on the frame rate is treated as steady state.
-- t0 is the presentation time of the last frame counted, so that (f_end - f0)
-- and (t_end - t0) cover exactly the same span - taking the poll's own clock
-- would add up to a full sample period and skew a 3 s window by ~3 %.
local function start_measure(timeout)
    t0 = (frame_pos_t and frame_pos_t > t_play) and frame_pos_t or mp.get_time()
    f0 = frames_now()
    warm = t0 - t_play
    warm_timeout = timeout or false
end

-- Two adjacent windows of WARM_WIN agree within WARM_TOL -> the ramp is over.
-- Both windows need a minimum number of frames, so a very slow lane cannot be
-- declared stable from a couple of frames.
local function rate_settled(now)
    if now - t_play < WARMUP_MIN then return false end
    local r2, n2 = rate_between(now - WARM_WIN, now)
    local r1, n1 = rate_between(now - 2 * WARM_WIN, now - WARM_WIN)
    if not (r1 and r2) then return false end
    if n1 < WARM_MIN_FRM or n2 < WARM_MIN_FRM then return false end
    return math.abs(r2 - r1) / math.max(r1, r2) <= WARM_TOL
end

timer = mp.add_periodic_timer(SAMPLE_PERIOD, function()
    if done or not t_play then return end
    local now = mp.get_time()
    local f = frames_now()
    add_sample(now, f)

    if not t0 then
        if rate_settled(now) then
            start_measure(false)
        elseif now - t_play >= WARMUP_MAX then
            -- Still hunting for a flat rate on a very slow lane: measure the
            -- rest anyway and flag the row instead of losing the run.
            start_measure(true)
        end
        return
    end

    -- Enough post-settling data: report and stop early so a slow lane does not
    -- burn the whole --frames budget just to reach the same average.
    if (now - t0) >= MEASURE_MIN_S and (f - f0) >= MEASURE_MIN_F then
        early_quit = true
        report()
        mp.command("quit")
    end
end)
timer:stop()   -- only runs after playback has started

mp.register_event("playback-restart", function()
    if t_play then return end
    t_play = mp.get_time()
    frame_pos = 0
    frame_pos_t = nil
    w = mp.get_property_number("video-out-params/w") or 0
    h = mp.get_property_number("video-out-params/h") or 0
    src = mp.get_property_number("container-fps") or mp.get_property_number("video-params/fps") or 0
    timer:resume()
end)

mp.register_event("end-file", function() report() end)

-- Fallback: still write a row when the run is cut short by Ctrl+C
mp.register_event("shutdown", function() report() end)

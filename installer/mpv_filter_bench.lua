-- mpv_filter_bench.lua
-- 补帧滤镜吞吐探针，由 installer\mpv-补帧滤镜跑分.bat 调用。
-- 计时口径：第一帧开始呈现（playback-restart）→ 达到 --frames 指定的输出帧数。
-- 这样 NGX/bridge 的一次性初始化不计入耗时，得到的是稳定吞吐。
-- 结果打印到终端，同时追加一行 TSV 到 MPV_BENCH_OUT 指定的文件。
--
-- 参数从环境变量读（mpv 会把脚本名里的 “-” 归一化成 “_”，script-opts 前缀不好写死）：
--   MPV_BENCH_TAG    结果行标签，如 VS-1080p
--   MPV_BENCH_OUT    TSV 输出文件（追加）
--   MPV_BENCH_MULTI  补帧倍数，用于把输出 fps 折算成等效源 fps

local mp = require "mp"

local function opt(env, key)
    local v = os.getenv(env)
    if v and v ~= "" then return v end
    return mp.get_opt(key)
end

local tag   = opt("MPV_BENCH_TAG", "tag") or "run"
local out   = opt("MPV_BENCH_OUT", "out") or ""
local multi = tonumber(opt("MPV_BENCH_MULTI", "multi") or "") or 0

local t0 = nil      -- 开始计时的 mpv 时间（秒）
local w, h, src = 0, 0, 0
local done = false

-- 片源先播完（没跑满 --frames）时，用媒体位置回推实际已经输出的帧数
local function count_frames(pos)
    local want = mp.get_property_number("options/frames") or 0
    local est = (pos and pos > 0 and src > 0 and multi > 0) and (pos * src * multi) or 0
    if want <= 0 then
        return math.floor(est + 0.5), est > 0
    end
    if est > 0 and est < want * 0.98 then
        return math.floor(est + 0.5), true     -- 片源不够长，按实际播到的位置折算
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
    print(string.format("[bench] %-12s %dx%d multi=%d %5d frames %6.2fs -> %7.1f out fps | %6.1f src fps %s",
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

-- 兜底：提前被 Ctrl+C 结束时也落一行
mp.register_event("shutdown", function() report() end)

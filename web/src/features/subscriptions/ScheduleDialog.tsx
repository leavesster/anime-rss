import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Save, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  listAnimeEpisodeHistory,
  syncSchedule,
  type Anime,
  updateAnimeSchedule,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import { ErrorBanner, LoadingState } from "../../shared/components/Feedback";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate } from "../../shared/lib/format";

const weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

export function ScheduleDialog({ anime, onClose }: { anime: Anime; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [airDate, setAirDate] = useState(anime.air_date ?? "");
  const [episodeCount, setEpisodeCount] = useState(anime.episode_count?.toString() ?? "");
  const [weekday, setWeekday] = useState(anime.airing_weekday?.toString() ?? "");
  const [airingTime, setAiringTime] = useState(anime.airing_time ?? "");
  const [timezone, setTimezone] = useState(anime.schedule_timezone ?? "Asia/Tokyo");
  const history = useQuery({
    queryKey: ["anime-episode-history", anime.id],
    queryFn: () => listAnimeEpisodeHistory(anime.id),
  });
  const save = useMutation({
    mutationFn: async () => {
      await updateAnimeSchedule(anime.id, {
        air_date: airDate || null,
        episode_count: episodeCount ? Number(episodeCount) : null,
        airing_weekday: weekday ? Number(weekday) : null,
        airing_time: airingTime || null,
        schedule_timezone: timezone,
      });
      await syncSchedule();
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["anime"] }),
        queryClient.invalidateQueries({ queryKey: ["anime-episode-history", anime.id] }),
        queryClient.invalidateQueries({ queryKey: ["schedule-calendar"] }),
      ]);
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="dialog dialog--wide" role="dialog" aria-modal="true" aria-labelledby="schedule-dialog-title">
        <header className="dialog__header">
          <div><h2 id="schedule-dialog-title">{anime.primary_title} · 播出计划</h2><p>日历只用于展示和缺集告警，不会触发下载。</p></div>
          <Button size="icon" variant="ghost" icon={<X size={18} />} aria-label="关闭" onClick={onClose} />
        </header>
        {save.isError && <ErrorBanner message={save.error.message} />}
        <form className="schedule-form" onSubmit={submit}>
          <label className="field"><span>首集日期</span><input type="date" value={airDate} onChange={(event) => setAirDate(event.target.value)} /></label>
          <label className="field"><span>总集数</span><input type="number" min={1} max={1000} value={episodeCount} onChange={(event) => setEpisodeCount(event.target.value)} /></label>
          <label className="field"><span>播出星期</span><select value={weekday} onChange={(event) => setWeekday(event.target.value)}><option value="">未设置</option>{weekdays.map((label, index) => <option value={index} key={label}>{label}</option>)}</select></label>
          <label className="field"><span>播出时间</span><input type="time" value={airingTime} onChange={(event) => setAiringTime(event.target.value)} /></label>
          <label className="field"><span>节目时区</span><input value={timezone} onChange={(event) => setTimezone(event.target.value)} /></label>
          <div className="schedule-form__action"><Button type="submit" variant="primary" icon={<Save size={16} />} disabled={save.isPending}>保存并刷新日历</Button></div>
        </form>
        <section className="schedule-history">
          <div className="section-heading"><div><h3>剧集历史</h3><p>按预计播出时间倒序</p></div></div>
          {history.isLoading && <LoadingState label="正在读取剧集历史" />}
          {history.isError && <ErrorBanner message="剧集历史加载失败。" />}
          {history.data?.length === 0 && <EmptyState icon={CalendarClock} title="还没有计划条目" description="保存完整的日期和时间后会生成预期集数。" />}
          <div className="schedule-history__list">
            {history.data?.map((episode) => (
              <article key={episode.id}>
                <div><strong>第 {episode.episode_key} 集</strong><small>{formatDate(episode.expected_at)}</small></div>
                <StatusBadge status={episode.state} />
              </article>
            ))}
          </div>
        </section>
      </section>
    </div>
  );
}

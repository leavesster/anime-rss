import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Pencil, Save, Trash2, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import {
  deleteEpisodeScheduleOverride,
  listAnimeEpisodeHistory,
  listEpisodeScheduleOverrides,
  saveEpisodeScheduleOverride,
  syncSchedule,
  type Anime,
  type EpisodeScheduleOverride,
  updateAnimeSchedule,
} from "../../generated/api/client";
import { Button } from "../../shared/components/Button";
import { EmptyState } from "../../shared/components/EmptyState";
import {
  ErrorBanner,
  LoadingState,
  SuccessBanner,
} from "../../shared/components/Feedback";
import { StatusBadge } from "../../shared/components/StatusBadge";
import { formatDate } from "../../shared/lib/format";

const weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

function toLocalDateTime(value: string): string {
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function ScheduleDialog({ anime, onClose }: { anime: Anime; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [airDate, setAirDate] = useState(anime.air_date ?? "");
  const [episodeCount, setEpisodeCount] = useState(anime.episode_count?.toString() ?? "");
  const [weekday, setWeekday] = useState(anime.airing_weekday?.toString() ?? "");
  const [airingTime, setAiringTime] = useState(anime.airing_time ?? "");
  const [timezone, setTimezone] = useState(anime.schedule_timezone ?? "Asia/Tokyo");
  const [overrideKey, setOverrideKey] = useState("");
  const [overrideTime, setOverrideTime] = useState("");
  const [overrideCancelled, setOverrideCancelled] = useState(false);
  const [overrideNote, setOverrideNote] = useState("");
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const history = useQuery({
    queryKey: ["anime-episode-history", anime.id],
    queryFn: () => listAnimeEpisodeHistory(anime.id),
  });
  const overrides = useQuery({
    queryKey: ["anime-schedule-overrides", anime.id],
    queryFn: () => listEpisodeScheduleOverrides(anime.id),
  });

  const refreshProjection = async () => {
    await syncSchedule();
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["anime-episode-history", anime.id] }),
      queryClient.invalidateQueries({ queryKey: ["anime-schedule-overrides", anime.id] }),
      queryClient.invalidateQueries({ queryKey: ["schedule-calendar"] }),
      queryClient.invalidateQueries({ queryKey: ["schedule-missing"] }),
    ]);
  };

  const save = useMutation({
    mutationFn: async () => {
      await updateAnimeSchedule(anime.id, anime.version, {
        air_date: airDate || null,
        episode_count: episodeCount ? Number(episodeCount) : null,
        airing_weekday: weekday ? Number(weekday) : null,
        airing_time: airingTime || null,
        schedule_timezone: timezone,
      });
      await refreshProjection();
    },
    onSuccess: async () => {
      setSuccess("基础播出计划已保存。");
      await queryClient.invalidateQueries({ queryKey: ["anime"] });
    },
  });

  const resetOverrideForm = () => {
    setOverrideKey("");
    setOverrideTime("");
    setOverrideCancelled(false);
    setOverrideNote("");
    setEditingKey(null);
  };

  const overrideSave = useMutation({
    mutationFn: async () => {
      const existing = overrides.data?.find((item) => item.episode_key === editingKey);
      await saveEpisodeScheduleOverride(
        anime.id,
        overrideKey,
        {
          expected_at: overrideCancelled ? null : new Date(overrideTime).toISOString(),
          cancelled: overrideCancelled,
          source: "manual",
          note: overrideNote || null,
        },
        existing?.version,
      );
      await refreshProjection();
    },
    onSuccess: () => {
      setSuccess("逐集调整已保存并刷新日历。");
      resetOverrideForm();
    },
  });

  const overrideDelete = useMutation({
    mutationFn: async (item: EpisodeScheduleOverride) => {
      await deleteEpisodeScheduleOverride(anime.id, item.episode_key, item.version);
      await refreshProjection();
      return item;
    },
    onSuccess: (item) => {
      if (editingKey === item.episode_key) resetOverrideForm();
      setSuccess(`第 ${item.episode_key} 集调整已删除。`);
    },
  });

  const editOverride = (item: EpisodeScheduleOverride) => {
    setEditingKey(item.episode_key);
    setOverrideKey(item.episode_key);
    setOverrideTime(item.expected_at ? toLocalDateTime(item.expected_at) : "");
    setOverrideCancelled(item.cancelled);
    setOverrideNote(item.note ?? "");
    setSuccess(null);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSuccess(null);
    save.mutate();
  };
  const submitOverride = (event: FormEvent) => {
    event.preventDefault();
    setSuccess(null);
    overrideSave.mutate();
  };
  const commandError = save.error ?? overrideSave.error ?? overrideDelete.error;

  return (
    <div
      className="dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="dialog dialog--wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="schedule-dialog-title"
      >
        <header className="dialog__header">
          <div>
            <h2 id="schedule-dialog-title">{anime.primary_title} · 播出计划</h2>
            <p>日历只用于展示和缺集告警，不会触发下载。</p>
          </div>
          <Button
            size="icon"
            variant="ghost"
            icon={<X size={18} />}
            aria-label="关闭"
            onClick={onClose}
          />
        </header>
        {commandError && <ErrorBanner message={commandError.message} />}
        {success && <SuccessBanner message={success} />}

        <form className="schedule-form" onSubmit={submit}>
          <label className="field">
            <span>首集日期</span>
            <input type="date" value={airDate} onChange={(event) => setAirDate(event.target.value)} />
          </label>
          <label className="field">
            <span>总集数</span>
            <input type="number" min={1} max={1000} value={episodeCount} onChange={(event) => setEpisodeCount(event.target.value)} />
          </label>
          <label className="field">
            <span>播出星期</span>
            <select value={weekday} onChange={(event) => setWeekday(event.target.value)}>
              <option value="">未设置</option>
              {weekdays.map((label, index) => <option value={index} key={label}>{label}</option>)}
            </select>
          </label>
          <label className="field">
            <span>播出时间</span>
            <input type="time" value={airingTime} onChange={(event) => setAiringTime(event.target.value)} />
          </label>
          <label className="field">
            <span>节目时区</span>
            <input value={timezone} onChange={(event) => setTimezone(event.target.value)} />
          </label>
          <div className="schedule-form__action">
            <Button type="submit" variant="primary" icon={<Save size={16} />} disabled={save.isPending}>
              保存并刷新日历
            </Button>
          </div>
        </form>

        <section className="schedule-overrides">
          <div className="section-heading">
            <div><h3>逐集调整</h3><p>延期、双集、特殊篇与停播</p></div>
          </div>
          <form className="schedule-override-form" onSubmit={submitOverride}>
            <label className="field">
              <span>集数标识</span>
              <input
                required
                maxLength={52}
                value={overrideKey}
                disabled={editingKey !== null}
                placeholder="12 / SP1 / OVA1"
                onChange={(event) => setOverrideKey(event.target.value)}
              />
            </label>
            <label className="field">
              <span>预计播出时间</span>
              <input
                type="datetime-local"
                required={!overrideCancelled}
                disabled={overrideCancelled}
                value={overrideTime}
                onChange={(event) => setOverrideTime(event.target.value)}
              />
            </label>
            <label className="field schedule-override-note">
              <span>备注</span>
              <input maxLength={500} value={overrideNote} onChange={(event) => setOverrideNote(event.target.value)} />
            </label>
            <label className="toggle-line schedule-override-cancelled">
              <input
                type="checkbox"
                checked={overrideCancelled}
                onChange={(event) => setOverrideCancelled(event.target.checked)}
              />
              <span><strong>停播或取消</strong></span>
            </label>
            <div className="schedule-override-actions">
              {editingKey && (
                <Button type="button" variant="ghost" icon={<X size={16} />} onClick={resetOverrideForm}>
                  取消编辑
                </Button>
              )}
              <Button type="submit" variant="primary" icon={<Save size={16} />} disabled={overrideSave.isPending}>
                保存逐集调整
              </Button>
            </div>
          </form>
          {overrides.isLoading && <LoadingState label="正在读取逐集调整" />}
          {overrides.isError && <ErrorBanner message="逐集调整加载失败。" />}
          {overrides.data?.length === 0 && <p className="inline-note schedule-overrides__empty">暂无逐集调整。</p>}
          <div className="schedule-override-list">
            {overrides.data?.map((item) => (
              <article key={item.id}>
                <div className="schedule-override-key"><strong>第 {item.episode_key} 集</strong><small>{item.source}</small></div>
                <div className="schedule-override-time"><strong>{item.cancelled ? "停播 / 取消" : formatDate(item.expected_at ?? "")}</strong><small>{item.note || "无备注"}</small></div>
                <div className="schedule-override-row-actions">
                  <Button size="icon" variant="ghost" icon={<Pencil size={16} />} aria-label={`编辑第 ${item.episode_key} 集调整`} onClick={() => editOverride(item)} />
                  <Button size="icon" variant="danger" icon={<Trash2 size={16} />} aria-label={`删除第 ${item.episode_key} 集调整`} disabled={overrideDelete.isPending} onClick={() => overrideDelete.mutate(item)} />
                </div>
              </article>
            ))}
          </div>
        </section>

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

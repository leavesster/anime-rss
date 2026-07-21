import {
  Check,
  Download,
  Eye,
  Languages,
  ListChecks,
  Radio,
  Rss,
  SlidersHorizontal,
} from "lucide-react";

export const splitList = (value: string) =>
  value.split(",").map((item) => item.trim()).filter(Boolean);

export const SETUP_STEPS = [
  { id: "administrator", label: "管理员", icon: Check },
  { id: "instance_preferences", label: "地区", icon: Languages },
  { id: "qbittorrent_connection", label: "qBittorrent", icon: Download },
  { id: "download_defaults", label: "下载默认值", icon: ListChecks },
  { id: "feed", label: "订阅源", icon: Rss },
  { id: "global_preferences", label: "版本偏好", icon: SlidersHorizontal },
  { id: "subscription", label: "首个追番", icon: Radio },
  { id: "candidate_preview", label: "候选预览", icon: Eye },
] as const;

export type SetupStepId = (typeof SETUP_STEPS)[number]["id"];

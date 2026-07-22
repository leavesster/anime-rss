import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  GitCompareArrows,
  Hand,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

const steps = [
  {
    icon: ShieldCheck,
    title: "直接排除",
    detail: "只接受识别可信度高的单集版本；默认要求中文字幕、1080p/720p 和 HEVC/AVC/AV1。",
  },
  {
    icon: GitCompareArrows,
    title: "依次比较",
    detail: "字幕组 -> 字幕 -> 清晰度 -> 编码 -> 高版本 -> 首次发现时间。前项优先级更高。",
  },
  {
    icon: Clock3,
    title: "等待或决定",
    detail: "所有首选条件都满足时立即选择；否则继续等待，期间只保留更好的版本，等待到期时间不会延后。",
  },
  {
    icon: RefreshCw,
    title: "版本升级",
    detail: "选择后仅接受同字幕组的 V2、V3 等修订版自动升级；其他字幕组不会覆盖已有选择。",
  },
];

export function SelectionLogicPanel() {
  return (
    <section className="selection-logic" aria-labelledby="selection-logic-title">
      <div className="section-heading selection-logic__heading">
        <div>
          <h2 id="selection-logic-title">当前选择逻辑</h2>
          <p>每一集独立选择；可接受范围决定哪些版本能参与，偏好顺序决定优先选择谁。</p>
        </div>
      </div>

      <div className="selection-flow">
        {steps.map(({ icon: Icon, title, detail }, index) => (
          <div className="selection-flow__step" data-testid="selection-step" key={title}>
            <div className="selection-flow__title">
              <span className="selection-flow__icon"><Icon size={17} /></span>
              <div><small>步骤 {index + 1}</small><strong>{title}</strong></div>
            </div>
            <p>{detail}</p>
            {index < steps.length - 1 && <ArrowRight className="selection-flow__arrow" size={16} aria-hidden="true" />}
          </div>
        ))}
      </div>

      <div className="manual-boundary">
        <span className="manual-boundary__icon"><Hand size={17} /></span>
        <div>
          <strong>手动操作说明</strong>
          <p><CheckCircle2 size={14} />已支持标题确认、补番和逐集改选。</p>
          <p>手动替换会保留之前的选择记录；重置不会删除 qBittorrent 中已有任务。</p>
        </div>
      </div>
    </section>
  );
}

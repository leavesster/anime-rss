import { AlertCircle, CheckCircle2, LoaderCircle } from "lucide-react";

export function LoadingState({ label = "正在加载" }: { label?: string }) {
  return (
    <div className="loading-state"><LoaderCircle className="spin" size={18} />{label}</div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="error-banner" role="alert"><AlertCircle size={18} />{message}</div>
  );
}

export function SuccessBanner({ message }: { message: string }) {
  return (
    <div className="success-banner" role="status"><CheckCircle2 size={18} />{message}</div>
  );
}

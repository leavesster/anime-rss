import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, LockKeyhole, Radio } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import {
  ApiError,
  getAuthStatus,
  login,
  setupAdministrator,
} from "../generated/api/client";
import { Button } from "../shared/components/Button";
import { ErrorBanner } from "../shared/components/Feedback";

export function AuthGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const status = useQuery({
    queryKey: ["auth-status"],
    queryFn: getAuthStatus,
    retry: false,
    staleTime: 0,
  });

  useEffect(() => {
    const refresh = () => queryClient.invalidateQueries({ queryKey: ["auth-status"] });
    window.addEventListener("anime-rss-auth-required", refresh);
    return () => window.removeEventListener("anime-rss-auth-required", refresh);
  }, [queryClient]);

  if (status.isLoading) {
    return (
      <div className="auth-screen auth-screen--loading">
        <LoaderCircle className="spin" size={24} />
        <span>正在连接服务</span>
      </div>
    );
  }
  if (status.isError || !status.data) {
    return (
      <div className="auth-screen">
        <div className="auth-panel">
          <ErrorBanner message="无法读取服务状态。" />
          <Button variant="primary" onClick={() => status.refetch()}>重新连接</Button>
        </div>
      </div>
    );
  }
  if (!status.data.enabled || status.data.authenticated) return children;
  return <AuthForm setupRequired={status.data.setup_required} />;
}

function AuthForm({ setupRequired }: { setupRequired: boolean }) {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const authenticate = useMutation({
    mutationFn: () =>
      setupRequired
        ? setupAdministrator(username, password)
        : login(username, password),
    onSuccess: async () => {
      setPassword("");
      setConfirmation("");
      await queryClient.invalidateQueries({ queryKey: ["auth-status"] });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (setupRequired && password !== confirmation) return;
    authenticate.mutate();
  };
  const mismatch = setupRequired && confirmation.length > 0 && password !== confirmation;
  const error = authenticate.error;
  const errorMessage = error instanceof ApiError ? error.message : "认证未完成，请重试。";

  return (
    <div className="auth-screen">
      <main className="auth-panel">
        <div className="auth-brand">
          <span className="brand__mark"><Radio size={22} /></span>
          <div><strong>Anime RSS</strong><span>自动追番服务</span></div>
        </div>
        <div className="auth-heading">
          <span><LockKeyhole size={19} /></span>
          <div>
            <h1>{setupRequired ? "设置管理员" : "管理员登录"}</h1>
            <p>{setupRequired ? "首次启动" : "会话已过期"}</p>
          </div>
        </div>
        {authenticate.isError && <ErrorBanner message={errorMessage} />}
        <form className="form-stack" onSubmit={submit}>
          <label className="field">
            <span>用户名</span>
            <input
              autoComplete="username"
              maxLength={80}
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>
          <label className="field">
            <span>密码</span>
            <input
              autoComplete={setupRequired ? "new-password" : "current-password"}
              minLength={12}
              maxLength={256}
              required
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {setupRequired && (
            <label className="field">
              <span>确认密码</span>
              <input
                aria-invalid={mismatch}
                autoComplete="new-password"
                minLength={12}
                maxLength={256}
                required
                type="password"
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
              />
              {mismatch && <small className="field-error">两次输入的密码不一致</small>}
            </label>
          )}
          <Button
            type="submit"
            variant="primary"
            icon={authenticate.isPending ? <LoaderCircle className="spin" size={16} /> : <LockKeyhole size={16} />}
            disabled={authenticate.isPending || mismatch}
          >
            {setupRequired ? "完成设置" : "登录"}
          </Button>
        </form>
      </main>
    </div>
  );
}

import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const login = useAuthStore((s) => s.login);
  const navigate = useNavigate();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/");
    } catch {
      setError("Invalid email or password");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <img src="/favicon.svg" alt="DeepOdds" className="w-14 h-14 mb-3" />
          <div className="flex flex-col items-center -space-y-0.5">
            <span className="text-2xl font-bold tracking-tight text-white">Deep<span className="text-emerald-400">Odds</span></span>
            <span className="text-[10px] font-medium uppercase tracking-[0.15em] text-slate-500">Trading Bot</span>
          </div>
        </div>
        <form
          onSubmit={handleSubmit}
          className="bg-slate-900 rounded-xl p-6 space-y-4 border border-slate-800"
        >
          <h2 className="text-xl font-semibold text-white">Sign in</h2>
          {error && (
            <p className="text-red-400 text-sm bg-red-400/10 rounded-lg p-3">
              {error}
            </p>
          )}
          <div>
            <label className="block text-sm text-slate-400 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:bg-emerald-800 text-white font-medium py-2 rounded-lg transition-colors"
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
          {/* registration disabled (single-tenant) — re-enable with multi-tenant work
          <p className="text-sm text-slate-400 text-center">
            Don't have an account?{" "}
            <Link to="/register" className="text-emerald-400 hover:underline">
              Register
            </Link>
          </p> */}
        </form>
      </div>
    </div>
  );
}

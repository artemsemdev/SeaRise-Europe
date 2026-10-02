import { spawn } from "node:child_process";
import { once } from "node:events";
import { clearTimeout, setTimeout } from "node:timers";

async function reap(child) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
  const exited = once(child, "exit");
  const force = setTimeout(() => child.kill("SIGKILL"), 2_000);
  force.unref();
  try { child.kill("SIGTERM"); await exited; } finally { clearTimeout(force); }
}

// Own native processes from spawn, including the interval before adapter readiness.
export function createLifecycle() {
  const children = new Set();
  const closers = [];
  let closing;
  let interrupted = false;
  const close = () => (closing ??= (async () => {
    for (const closer of [...closers].reverse()) {
      try { await closer(); } catch { /* Reap native children even if preview shutdown fails. */ }
    }
    await Promise.all([...children].map(reap));
  })());
  const stop = () => { interrupted = true; void close().then(() => process.exit(0), () => process.exit(1)); };
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, stop);
  return {
    get interrupted() { return interrupted; },
    spawn(executable, args, options) {
      if (closing || interrupted) throw new Error("Demo startup interrupted.");
      const child = spawn(executable, args, options);
      children.add(child);
      child.once("exit", () => children.delete(child));
      return child;
    },
    addCloser(closer) { closers.push(closer); },
    close,
    dispose() { for (const signal of ["SIGINT", "SIGTERM"]) process.removeListener(signal, stop); },
  };
}

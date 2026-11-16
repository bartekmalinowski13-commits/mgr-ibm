export type StepKey = "project" | "run" | "review";

export function firstBomSteps(c: { projects: number; runs: number; completed: number }) {
  const steps: { key: StepKey; done: boolean }[] = [
    { key: "project", done: c.projects > 0 },
    { key: "run", done: c.runs > 0 },
    { key: "review", done: c.completed > 0 },
  ];
  const open = steps.find((s) => !s.done);
  return { steps, next: open?.key ?? null, complete: !open };
}

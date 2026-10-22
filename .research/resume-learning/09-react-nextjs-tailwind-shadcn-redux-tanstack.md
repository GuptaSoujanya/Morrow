# React, Next.js, Tailwind, shadcn/ui, Redux Toolkit, TanStack Query

## What it is

This is the front-end stack used for the dashboards and admin UIs described on the resume: **React** as the component model, **Next.js** as the framework providing routing/rendering/build tooling on top of React, **Tailwind CSS** for utility-first styling, **shadcn/ui** as a copy-into-your-codebase component library built on Tailwind and Radix primitives, **Redux Toolkit** for centralized client-side state when it's genuinely needed, and **TanStack Query** for server-state management (fetching, caching, and synchronizing data from an API) - a distinct concern from client state that Redux is not actually designed to solve well.

## How you used it

The resume describes two concrete front-end deliverables. First, **the model-training UI for a major technology client in Next.js, React, and Tailwind CSS, with a reusable component library, real-time training-metric dashboards, and code splitting for fast page loads**. Second, **the front-end for the Kuberha AI website and admin dashboard in Next.js, Tailwind CSS, and shadcn/ui, now running in production with role-based access**. Redux Toolkit and TanStack Query appear in the skills list under Web, implying they were part of the state-management layer backing these dashboards - Redux Toolkit for shared client state (e.g., UI state, role/permission state), and TanStack Query for the real-time training-metric data fetching/caching that a live dashboard depends on.

## Core concepts

**1. Why Next.js on top of plain React for dashboards.** Next.js provides file-based routing, built-in code splitting per route, server-side rendering/static generation options, and an opinionated project structure - all of which reduce the boilerplate a dashboard team would otherwise hand-build on top of bare React (a router, a bundler config, a data-fetching convention).

```tsx
// app/dashboard/training-metrics/page.tsx (Next.js App Router)
export default function TrainingMetricsPage() {
  return <TrainingMetricsDashboard />;
}
```

Next.js automatically code-splits at the route/page boundary, which is the mechanical basis of the "code splitting for fast page loads" bullet - each route's JavaScript bundle loads only when that route is visited, rather than shipping the entire application's code on first load.

**2. Reusable component libraries.** A "reusable component library" in this context usually means a shared set of primitive and composite components (buttons, cards, tables, chart wrappers, form fields) with consistent styling and props APIs, used across every page of the dashboard rather than each page re-implementing its own button or table styling. shadcn/ui is a specific approach to this: rather than installing it as an opaque npm dependency, you copy the component source into your own codebase (via its CLI), so the components are fully yours to customize.

```bash
npx shadcn@latest add button card table
```

```tsx
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardHeader><CardTitle>{label}</CardTitle></CardHeader>
      <CardContent className="text-2xl font-semibold">{value}</CardContent>
    </Card>
  );
}
```

**3. Tailwind's utility-first model.** Instead of writing separate CSS files with custom class names, Tailwind applies styling via composable utility classes directly in markup. This pairs naturally with a component library approach: you build the styled primitive once (as above) and reuse it, rather than writing Tailwind classes ad hoc on every page.

**4. Real-time training-metric dashboards.** A dashboard showing live training metrics (loss curves, throughput, GPU utilization) needs a data layer that can refresh on an interval or via a push mechanism (WebSocket/SSE) and a rendering layer that updates charts without a full page reload. TanStack Query is the natural fit for the polling case:

```tsx
import { useQuery } from "@tanstack/react-query";

function useTrainingMetrics(runId: string) {
  return useQuery({
    queryKey: ["training-metrics", runId],
    queryFn: () => fetch(`/api/runs/${runId}/metrics`).then((r) => r.json()),
    refetchInterval: 5000, // poll every 5s for "real-time" updates
  });
}

function MetricsChart({ runId }: { runId: string }) {
  const { data, isLoading } = useTrainingMetrics(runId);
  if (isLoading) return <Skeleton />;
  return <LineChart data={data.points} />;
}
```

For genuinely push-based real-time updates, a WebSocket connection feeding into TanStack Query's cache via `queryClient.setQueryData` is a common pattern, combining a live push channel with Query's caching/loading-state machinery rather than managing a separate ad hoc state store for streamed data.

**5. Why TanStack Query instead of (or alongside) Redux for this data.** Server state - data that lives on a server and can go stale - has different needs than client state: it needs caching, deduplication of in-flight requests, background refetching, and loading/error states tracked per query. Redux (even with Redux Toolkit's improvements) makes you build all of that by hand; TanStack Query provides it out of the box. The practical split: TanStack Query owns "what does the server say right now" (training metrics, user lists), Redux Toolkit owns genuinely client-only state that doesn't come from a server call (current UI theme, multi-step form state, the current user's role/permission flags once fetched).

```ts
// Redux Toolkit slice for client-only state
import { createSlice } from "@reduxjs/toolkit";

const uiSlice = createSlice({
  name: "ui",
  initialState: { sidebarCollapsed: false },
  reducers: {
    toggleSidebar: (state) => { state.sidebarCollapsed = !state.sidebarCollapsed; },
  },
});
```

**6. Role-based access in an admin dashboard.** The Kuberha AI admin dashboard's role-based access means different users see different routes/components based on a role claim, typically checked both client-side (hide/disable UI the user shouldn't use) and enforced server-side (the actual API must also reject unauthorized requests - client-side checks are a UX convenience, never a security boundary on their own).

```tsx
function RequireRole({ role, children }: { role: string; children: React.ReactNode }) {
  const { data: user } = useCurrentUser(); // TanStack Query-backed
  if (!user?.roles.includes(role)) return <Forbidden />;
  return <>{children}</>;
}
```

```tsx
// Next.js middleware can also gate entire route segments before rendering
export function middleware(request: NextRequest) {
  const role = getRoleFromSession(request);
  if (request.nextUrl.pathname.startsWith("/admin") && role !== "admin") {
    return NextResponse.redirect(new URL("/forbidden", request.url));
  }
}
```

**7. Code splitting beyond the automatic route-level split.** For a component that's large but rarely needed (a heavy charting library, a rich text editor), `dynamic()` imports in Next.js split that component into its own chunk loaded only when rendered, rather than bundled into the initial page load even if the route itself is small:

```tsx
import dynamic from "next/dynamic";

const HeavyChart = dynamic(() => import("@/components/HeavyChart"), { ssr: false });
```

**8. shadcn/ui versus a traditional component library.** Traditional libraries (Material UI, Ant Design) ship as compiled npm packages you style via theming APIs or CSS overrides. shadcn/ui instead gives you the actual component source (built on Radix UI primitives for accessibility behavior, styled with Tailwind) copied into your project, so customizing a component's markup or behavior is a direct code edit rather than fighting a theming API - useful for a "reusable component library" you expect to diverge from the defaults over time.

## Interview questions and answers

**Q1: Why Next.js instead of plain React with a router library for a dashboard like this?**
Next.js gives file-based routing, automatic per-route code splitting, and built-in rendering strategy choices (SSR, SSG, client rendering) without assembling that from separate libraries. For a dashboard where fast page loads mattered, the automatic code splitting alone removes a whole category of manual bundle-configuration work.

**Q2: How did you build "real-time" training-metric dashboards - true push updates or polling?**
In practice this is often a mix: TanStack Query's `refetchInterval` handles the common polling case cleanly with built-in caching and loading states, and where truly live push updates matter, a WebSocket feed updates the Query cache directly via `setQueryData` so the UI still benefits from Query's caching and stale-state handling rather than maintaining a parallel ad hoc state store.

**Q3: What's the actual difference between Redux Toolkit and TanStack Query, and why use both?**
TanStack Query manages server state - data fetched from an API, with built-in caching, deduplication, and refetching - while Redux Toolkit manages client-only state that doesn't come from a server call. Using TanStack Query for server data and Redux (or even just React context) for UI-only state avoids reimplementing caching/loading logic by hand in Redux, which isn't designed for that problem.

**Q4: How do you implement role-based access correctly across a Next.js admin dashboard?**
Client-side, hide or disable UI elements based on the user's role for a good UX, typically via a `RequireRole` wrapper or Next.js middleware that redirects unauthorized route access before rendering. Critically, the same role check must also be enforced server-side on every API endpoint - client-side gating is a UX nicety, not a security control, since a client can always be bypassed.

**Q5: What's the benefit of shadcn/ui's "copy the source into your project" model over a traditional installed component library?**
You get full control over the component's markup, styling, and behavior as plain code in your repo rather than working through a theming/override API, which matters when a "reusable component library" needs to diverge meaningfully from defaults over time - you're not fighting someone else's abstraction to get a bespoke look.

**Q6: How do you decide what belongs in Redux Toolkit versus local component state (`useState`)?**
If the state is only relevant to one component and its direct children, local state is simpler and avoids unnecessary global re-renders. Redux Toolkit earns its place when state needs to be read or updated from distant, unrelated parts of the component tree - cross-cutting UI state like sidebar collapse, global filters, or session/role info fetched once and used everywhere.

**Q7: What's the mechanism behind Next.js's automatic code splitting, and when do you need manual `dynamic()` imports on top of it?**
Next.js automatically splits JavaScript at route boundaries, so visiting one page doesn't download the code for every other page. Manual `dynamic()` imports are for splitting within a single page - a heavy component (chart library, rich editor) that isn't needed on initial render or is conditionally shown, so its bundle only loads when actually rendered.

**Q8: How would you test a component that depends on TanStack Query data?**
Wrap the component under test in a `QueryClientProvider` with a test `QueryClient` (usually configured with retries disabled and a short/zero cache time), and either mock the fetch function or use a tool like MSW to intercept the network call, so the test exercises real Query behavior (loading state, then resolved data) without hitting a real backend.

**Q9: What would you watch for if a "real-time" dashboard started feeling sluggish under many concurrent metric streams?**
Check whether the polling interval is too aggressive relative to how often the underlying data actually changes, whether chart re-renders are happening on every poll even when data is unchanged (memoizing chart components or comparing data references can help), and whether too many independent queries are firing instead of batching related metrics into fewer requests.

**Q10: Walk me through how you'd add a new admin-only page with proper access control in this stack.**
Add the route under an `/admin` segment, add a Next.js middleware (or layout-level) check that redirects non-admin roles before the page renders, build the page's UI from the shared shadcn/ui component library for consistency, fetch any server data through a TanStack Query hook, and - separately and non-negotiably - add the equivalent role check to the backend API endpoints the page calls, since the frontend check alone is not a security boundary.

## Hands-on

1. **Build a small polling dashboard.** Create a Next.js page with a TanStack Query hook that polls a mock `/api/metrics` route every 3 seconds and renders the latest value in a shadcn/ui `Card`, then verify in the browser dev tools that requests actually fire on the expected interval and that navigating away stops them.
2. **Add role-gated middleware.** Write a Next.js middleware function that reads a mock role from a cookie and redirects any request to `/admin/*` to a `/forbidden` page unless the role is `"admin"`, then test both an authorized and unauthorized request path.

## Read next

- [Next.js documentation](https://nextjs.org/docs)
- [Tailwind CSS documentation](https://tailwindcss.com/docs)
- [shadcn/ui documentation](https://ui.shadcn.com/docs)
- [TanStack Query documentation](https://tanstack.com/query/latest/docs/framework/react/overview)
- [Redux Toolkit documentation](https://redux-toolkit.js.org/introduction/getting-started)
- [../../course/03-fullstack-mern-kubernetes/03-react-advanced.md](../../course/03-fullstack-mern-kubernetes/03-react-advanced.md)
- [../../course/03-fullstack-mern-kubernetes/05-fullstack-project-architecture.md](../../course/03-fullstack-mern-kubernetes/05-fullstack-project-architecture.md)

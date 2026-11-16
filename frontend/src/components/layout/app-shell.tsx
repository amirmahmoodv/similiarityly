import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Box,
  ChevronDown,
  ChevronLeft,
  Database,
  Languages,
  LayoutDashboard,
  Settings,
  TriangleAlert,
} from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { BootSequence } from "@/components/hud/boot-sequence";
import { FetchBar, usePointerEffects, WaveField } from "@/components/hud/effects";
import { Reactor, type ReactorState } from "@/components/hud/reactor";
import { PageTransition } from "@/components/motion";
import { useI18n } from "@/i18n";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { motionTokens, transitions } from "@/lib/motion";

const ACTIVE = new Set(["queued", "running"]);
const RAIL_KEY = "similarityly.rail";

const stateTone: Record<ReactorState, string> = {
  connecting: "text-muted-foreground",
  online: "text-primary",
  active: "text-sim",
  offline: "text-destructive",
};

function initialCollapsed(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "collapsed";
  } catch {
    return false;
  }
}

/** Text that fades out (and is clipped by the rail) when the sidebar is collapsed. */
const railText =
  "whitespace-nowrap transition-opacity duration-200 md:group-data-[collapsed=true]/shell:opacity-0";

const navLink =
  "group relative isolate flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium outline-none transition-colors md:px-4 " +
  "focus-visible:ring-2 focus-visible:ring-ring active:scale-[0.97] " +
  // Hover: a backing bar wipes in from the start edge.
  "before:absolute before:inset-0 before:-z-20 before:origin-left before:scale-x-0 before:rounded-lg before:bg-muted/70 before:transition-transform before:duration-300 hover:before:scale-x-100 rtl:before:origin-right";

export function AppShell() {
  const { t, n, dir, locale, setLocale } = useI18n();
  const location = useLocation();
  const reduceMotion = useReducedMotion();
  usePointerEffects();

  const [collapsed, setCollapsed] = React.useState(initialCollapsed);
  const [reposOpen, setReposOpen] = React.useState(true);
  const toggleRail = () => {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(RAIL_KEY, next ? "collapsed" : "expanded");
    } catch {
      /* storage unavailable: the choice just won't persist */
    }
  };

  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  // Same queries the pages use, so the cache is shared; jobs only poll while something is in flight.
  const jobs = useQuery({
    queryKey: ["jobs", "recent"],
    queryFn: () => api.jobs(undefined, 8),
    refetchInterval: (q) => (q.state.data?.some((j) => ACTIVE.has(j.status)) ? 1500 : false),
  });
  const repos = useQuery({ queryKey: ["repos"], queryFn: api.repos });

  const activeJobs = jobs.data?.filter((j) => ACTIVE.has(j.status)).length ?? 0;
  const state: ReactorState =
    meta.isError || jobs.isError
      ? "offline"
      : !meta.data
        ? "connecting"
        : activeJobs > 0
          ? "active"
          : "online";
  const stateText =
    state === "active" ? t.app.status.active(n(activeJobs)) : t.app.status[state];

  // Job pages belong to the repos section for navigation purposes.
  const section =
    location.pathname === "/"
      ? "/"
      : location.pathname.startsWith("/settings")
        ? "/settings"
        : "/repos";

  const repoList = repos.data ?? [];
  const showSubmenu = reposOpen && !collapsed && repoList.length > 0;

  const link = (to: string, label: string, Icon: typeof Database, end: boolean) => (
    <NavLink
      to={to}
      end={end}
      title={label}
      className={cn(
        navLink,
        "min-w-0 flex-1",
        section === to ? "text-primary" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {section === to && (
        <motion.span
          layoutId="nav-indicator"
          className="absolute inset-0 -z-10 overflow-hidden rounded-lg border border-primary/30 bg-accent/70 shadow-[0_0_22px_-10px_var(--primary)]"
          transition={reduceMotion ? { duration: 0.01 } : transitions.tactile}
        >
          <span className="absolute inset-y-1.5 start-0 w-0.5 rounded-full bg-primary shadow-[0_0_8px_var(--primary)]" />
        </motion.span>
      )}
      <Icon
        className="size-4 shrink-0 transition-transform duration-200 group-hover:scale-125 group-hover:text-primary"
        aria-hidden="true"
      />
      {/* Icon-only on narrow phones; the label stays the link's accessible name. */}
      <span
        className={cn(
          railText,
          "transition-[opacity,transform] group-hover:translate-x-1 max-sm:sr-only rtl:group-hover:-translate-x-1",
        )}
      >
        {label}
      </span>
    </NavLink>
  );

  return (
    <div
      data-collapsed={collapsed}
      className="group/shell min-h-dvh md:grid md:grid-cols-[15.5rem_1fr] md:transition-[grid-template-columns] md:duration-300 md:ease-[cubic-bezier(0.22,1,0.36,1)] md:data-[collapsed=true]:grid-cols-[5rem_1fr]"
    >
      <BootSequence name={t.app.name} />
      <FetchBar />
      <WaveField state={state} />

      <aside className="sticky top-0 z-30 flex items-center gap-3 border-b bg-card/70 px-4 py-3 backdrop-blur-md md:block md:h-dvh md:min-w-0 md:border-b-0 md:border-e md:p-0">
        {/* Lit edge between the console rail and the workspace. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 -end-px hidden w-px bg-linear-to-b from-transparent via-primary/70 to-transparent md:block"
        />
        <button
          type="button"
          onClick={toggleRail}
          aria-expanded={!collapsed}
          aria-label={collapsed ? t.nav.expand : t.nav.collapse}
          title={collapsed ? t.nav.expand : t.nav.collapse}
          className="absolute -end-3.5 top-9 z-10 hidden size-7 place-items-center rounded-full border border-primary/40 bg-card text-primary outline-none transition-[transform,box-shadow] duration-200 hover:scale-110 hover:shadow-[0_0_16px_-2px_var(--primary)] focus-visible:ring-2 focus-visible:ring-ring active:scale-90 md:grid"
        >
          <ChevronLeft
            className={cn(
              "size-4 transition-transform duration-300",
              // Points at the rail when it can collapse, away from it when it can expand.
              collapsed !== (dir === "rtl") && "rotate-180",
            )}
            aria-hidden="true"
          />
        </button>

        {/* A plain flex row on phones; on desktop the column that clips labels as the rail narrows. */}
        <div className="contents md:flex md:h-full md:flex-col md:overflow-x-hidden md:overflow-y-auto md:px-4 md:py-6">
          <div className="flex items-center gap-3 md:mb-8" title={stateText}>
            <Reactor state={state} className="size-10 md:size-12" />
            <div className={cn(railText, "hidden min-w-0 sm:block")}>
              <div className="hud-glow font-bold leading-tight text-primary">{t.app.name}</div>
              <div className="hud-label">{t.app.tagline}</div>
            </div>
          </div>

          <nav aria-label={t.nav.main} className="flex flex-1 gap-1 md:flex-none md:flex-col">
            {link("/", t.nav.dashboard, LayoutDashboard, true)}

            <div className="max-md:contents">
              <div className="flex items-center gap-1 max-md:contents">
                {link("/repos", t.nav.repos, Database, false)}
                {!collapsed && repoList.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setReposOpen((open) => !open)}
                    aria-expanded={reposOpen}
                    aria-controls="nav-repos"
                    aria-label={t.nav.toggleRepos}
                    title={t.nav.toggleRepos}
                    className="hidden size-8 shrink-0 place-items-center rounded-lg text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-primary focus-visible:ring-2 focus-visible:ring-ring active:scale-90 md:grid"
                  >
                    <ChevronDown
                      className={cn("size-4 transition-transform duration-300", reposOpen && "rotate-180")}
                      aria-hidden="true"
                    />
                  </button>
                )}
              </div>

              <AnimatePresence initial={false}>
                {showSubmenu && (
                  <motion.ul
                    id="nav-repos"
                    className="ms-5 overflow-hidden border-s border-primary/25 ps-2 max-md:hidden"
                    initial={reduceMotion ? { opacity: 0 } : { height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={reduceMotion ? { opacity: 0 } : { height: 0, opacity: 0 }}
                    transition={
                      reduceMotion
                        ? { duration: 0.01 }
                        : { duration: motionTokens.duration.panel, ease: motionTokens.ease.standard }
                    }
                  >
                    {repoList.map((repo, index) => (
                      <motion.li
                        key={repo.id}
                        initial={reduceMotion ? false : { opacity: 0, x: dir === "rtl" ? 10 : -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ ...transitions.standard, delay: Math.min(index, 8) * 0.035 }}
                      >
                        <NavLink
                          to={`/repos/${repo.id}`}
                          title={repo.name}
                          className={({ isActive }) =>
                            cn(
                              "group mt-0.5 flex items-center gap-2 rounded-md px-2 py-1.5 text-xs outline-none transition-colors hover:bg-muted/70 hover:text-primary focus-visible:ring-2 focus-visible:ring-ring",
                              isActive ? "bg-accent/60 text-primary" : "text-muted-foreground",
                            )
                          }
                        >
                          {repo.needs_reindex ? (
                            <TriangleAlert className="size-3.5 shrink-0 text-sim" aria-hidden="true" />
                          ) : (
                            <Box
                              className="size-3.5 shrink-0 transition-transform duration-200 group-hover:rotate-12 group-hover:scale-125"
                              aria-hidden="true"
                            />
                          )}
                          <span className="truncate">{repo.name}</span>
                        </NavLink>
                      </motion.li>
                    ))}
                  </motion.ul>
                )}
              </AnimatePresence>
            </div>

            {link("/settings", t.nav.settings, Settings, false)}
          </nav>

          <div className="flex items-center gap-2 md:mt-auto md:flex-col md:items-stretch md:pt-4">
            <div
              role="status"
              title={stateText}
              className="hidden rounded-lg border border-primary/15 bg-muted/60 px-3 py-2 text-xs md:block"
            >
              <div
                className={cn(
                  "flex items-center gap-2 font-medium",
                  collapsed && "justify-center py-1",
                  stateTone[state],
                )}
              >
                <span className="relative flex size-2 shrink-0">
                  {state === "active" && (
                    <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-60" />
                  )}
                  <span className="relative inline-flex size-2 rounded-full bg-current shadow-[0_0_8px_currentColor]" />
                </span>
                <span className={cn("nums whitespace-nowrap", collapsed && "sr-only")}>{stateText}</span>
              </div>
              {meta.data && !collapsed && (
                <div className="mt-1 whitespace-nowrap text-muted-foreground">
                  {t.app.qdrant[meta.data.qdrant_mode]}
                </div>
              )}
            </div>
            <button
              type="button"
              onClick={() => setLocale(locale === "fa" ? "en" : "fa")}
              title={t.app.switchLanguage}
              className="group flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground outline-none transition-[color,background-color,transform] hover:bg-muted hover:text-primary focus-visible:ring-2 focus-visible:ring-ring active:scale-95 md:justify-start md:px-4"
            >
              <Languages
                className="size-4 shrink-0 transition-transform duration-300 group-hover:rotate-[360deg]"
                aria-hidden="true"
              />
              <span className={railText}>{t.app.switchLanguage}</span>
            </button>
          </div>
        </div>
      </aside>

      <main className="min-w-0 px-4 py-6 md:px-8 md:py-8">
        <PageTransition transitionKey={location.pathname} className="mx-auto max-w-6xl">
          <Outlet />
        </PageTransition>
      </main>
    </div>
  );
}

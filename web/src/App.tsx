import { lazy, Suspense } from "react";
import { useQuery } from "@tanstack/react-query";
import { Redirect, Route, Switch } from "wouter";
import { currentUser } from "./api";
import Layout from "./components/Layout";

const ComparePage = lazy(() => import("./pages/ComparePage"));
const ConnectPage = lazy(() => import("./pages/ConnectPage"));
const JobsPage = lazy(() => import("./pages/JobsPage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const ProjectsPage = lazy(() => import("./pages/ProjectsPage"));
const PublicProjectPage = lazy(() => import("./pages/PublicProjectPage"));
const RunPage = lazy(() => import("./pages/RunPage"));
const RunsPage = lazy(() => import("./pages/RunsPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));

function PrivateApp() {
  const user = useQuery({ queryKey: ["me"], queryFn: currentUser });
  if (user.isPending) return <div className="center-state"><span className="spinner" />Loading Zephyr…</div>;
  if (user.isError) return <Redirect to="/login" replace />;
  return (
    <Layout user={user.data}>
      <Switch>
        <Route path="/" component={RunsPage} />
        <Route path="/runs/:runId" component={RunPage} />
        <Route path="/jobs" component={JobsPage} />
        <Route path="/compare" component={ComparePage} />
        <Route path="/projects" component={ProjectsPage} />
        <Route path="/settings/*?" component={SettingsPage} />
        <Route><Redirect to="/" replace /></Route>
      </Switch>
    </Layout>
  );
}

export default function App() {
  return (
    <Suspense fallback={<div className="center-state"><span className="spinner" />Loading Zephyr…</div>}>
      <Switch>
        <Route path="/connect/:code" component={ConnectPage} />
        <Route path="/login" component={LoginPage} />
        <Route path="/public/:slug/*?" component={PublicProjectPage} />
        <Route component={PrivateApp} />
      </Switch>
    </Suspense>
  );
}

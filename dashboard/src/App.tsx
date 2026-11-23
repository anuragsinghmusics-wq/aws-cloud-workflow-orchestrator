import React from "react";
import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { Navbar } from "./components/Navbar";
import { Sidebar } from "./components/Sidebar";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { DashboardOverview } from "./pages/DashboardOverview";
import { WorkflowsList } from "./pages/WorkflowsList";
import { WorkflowDetail } from "./pages/WorkflowDetail";
import { NewWorkflow } from "./pages/NewWorkflow";
import { ApiKeys } from "./pages/ApiKeys";
import { SystemHealth } from "./pages/SystemHealth";

const DashboardLayout: React.FC = () => {
  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 p-6 md:p-8 max-w-7xl mx-auto w-full">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public Routes */}
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        {/* Protected Dashboard Routes */}
        <Route element={<ProtectedRoute />}>
          <Route element={<DashboardLayout />}>
            <Route path="/" element={<DashboardOverview />} />
            <Route path="/workflows" element={<WorkflowsList />} />
            <Route path="/workflows/new" element={<NewWorkflow />} />
            <Route path="/workflows/:jobId" element={<WorkflowDetail />} />
            <Route path="/api-keys" element={<ApiKeys />} />
            <Route path="/health" element={<SystemHealth />} />
          </Route>
        </Route>

        {/* Catch-all redirect */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
};

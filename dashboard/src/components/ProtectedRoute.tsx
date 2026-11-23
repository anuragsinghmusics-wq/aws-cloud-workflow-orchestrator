import React from "react";
import { Navigate, Outlet } from "react-router-dom";
import { authService } from "../services/api";

export const ProtectedRoute: React.FC = () => {
  const isAuth = authService.isAuthenticated();

  if (!isAuth) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
};

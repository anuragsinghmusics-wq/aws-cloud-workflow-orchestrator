import axios, { AxiosError } from "axios";
import type {
  ApiKey,
  AuthTokens,
  SystemHealth,
  SystemMetrics,
  User,
  Workflow,
  WorkflowListResponse,
} from "../types";

export const api = axios.create({
  baseURL: "/api/v1",
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor: Attach access token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("cwo_access_token");
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor: Automatic token refresh on 401
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as typeof error.config & { _retry?: boolean };
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      const refreshToken = localStorage.getItem("cwo_refresh_token");
      if (refreshToken) {
        try {
          const res = await axios.post<AuthTokens>("/api/v1/auth/refresh", {
            refresh_token: refreshToken,
          });
          const { access_token, refresh_token } = res.data;
          localStorage.setItem("cwo_access_token", access_token);
          localStorage.setItem("cwo_refresh_token", refresh_token);
          if (originalRequest.headers) {
            originalRequest.headers.Authorization = `Bearer ${access_token}`;
          }
          return api(originalRequest);
        } catch {
          // Refresh failed -> clear session
          localStorage.removeItem("cwo_access_token");
          localStorage.removeItem("cwo_refresh_token");
          localStorage.removeItem("cwo_user");
          if (window.location.pathname !== "/login" && window.location.pathname !== "/register") {
            window.location.href = "/login";
          }
        }
      } else {
        localStorage.removeItem("cwo_access_token");
        localStorage.removeItem("cwo_user");
        if (window.location.pathname !== "/login" && window.location.pathname !== "/register") {
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(error);
  }
);

export const authService = {
  async login(email: string, password: string): Promise<AuthTokens> {
    const res = await api.post<AuthTokens>("/auth/login", { email, password });
    localStorage.setItem("cwo_access_token", res.data.access_token);
    localStorage.setItem("cwo_refresh_token", res.data.refresh_token);
    try {
      const profile = await this.getProfile();
      localStorage.setItem("cwo_user", JSON.stringify(profile));
    } catch {
      // Fallback user object if profile endpoint is delayed
      const fallbackUser: User = {
        id: "current-user",
        email: email,
        full_name: email.split("@")[0],
        role: "ADMIN",
        is_active: true,
        is_superuser: false,
        created_at: new Date().toISOString(),
      };
      localStorage.setItem("cwo_user", JSON.stringify(fallbackUser));
    }
    return res.data;
  },

  async register(email: string, password: string, fullName?: string, role = "OPERATOR"): Promise<User> {
    const res = await api.post<User>("/auth/register", {
      email,
      password,
      full_name: fullName,
      role,
    });
    return res.data;
  },

  async getProfile(): Promise<User> {
    const res = await api.get<User>("/auth/me");
    return res.data;
  },

  logout(): void {
    localStorage.removeItem("cwo_access_token");
    localStorage.removeItem("cwo_refresh_token");
    localStorage.removeItem("cwo_user");
    window.location.href = "/login";
  },

  getCurrentUser(): User | null {
    try {
      const userStr = localStorage.getItem("cwo_user");
      return userStr ? JSON.parse(userStr) : null;
    } catch {
      return null;
    }
  },

  isAuthenticated(): boolean {
    return !!localStorage.getItem("cwo_access_token");
  },
};

export const workflowService = {
  async listWorkflows(params?: {
    state?: string;
    search?: string;
    page?: number;
    page_size?: number;
  }): Promise<WorkflowListResponse> {
    const res = await api.get<WorkflowListResponse>("/workflows", { params });
    return res.data;
  },

  async getWorkflow(jobId: string): Promise<Workflow> {
    const res = await api.get<Workflow>(`/workflows/${jobId}`);
    return res.data;
  },

  async createWorkflow(payload: {
    workflow_name: string;
    source_type: string;
    target_dynamodb_table: string;
    payload_data: Record<string, unknown>[];
    configuration?: Record<string, unknown>;
  }): Promise<Workflow> {
    const res = await api.post<Workflow>("/workflows", payload);
    return res.data;
  },

  async retryWorkflow(jobId: string, reason?: string): Promise<Workflow> {
    const res = await api.post<Workflow>(`/workflows/${jobId}/retry`, { reason });
    return res.data;
  },

  async cancelWorkflow(jobId: string): Promise<Workflow> {
    const res = await api.post<Workflow>(`/workflows/${jobId}/cancel`);
    return res.data;
  },
};

export const metricsService = {
  async getMetrics(): Promise<SystemMetrics> {
    const res = await api.get<SystemMetrics>("/metrics");
    return res.data;
  },

  async getHealth(): Promise<SystemHealth> {
    const res = await api.get<SystemHealth>("/health/readiness");
    return res.data;
  },
};

export const apiKeyService = {
  async listApiKeys(): Promise<ApiKey[]> {
    const res = await api.get<ApiKey[]>("/auth/api-keys");
    return res.data;
  },

  async createApiKey(name: string): Promise<ApiKey> {
    const res = await api.post<ApiKey>("/auth/api-keys", { name });
    return res.data;
  },

  async revokeApiKey(id: string): Promise<void> {
    await api.delete(`/auth/api-keys/${id}`);
  },
};

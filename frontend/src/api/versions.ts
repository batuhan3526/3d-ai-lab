import { api } from "./client";
import type { Customizations } from "../types";

export type Version = {
  id: string;
  project_id: string;
  name: string;
  auto: boolean;
  customizations: Customizations;
  created_at: string;
};

export const listVersions = (projectId: string) =>
  api<Version[]>(`/projects/${projectId}/versions`);

export const createVersion = (projectId: string, name: string, customizations: Customizations, auto = false) =>
  api<Version>(`/projects/${projectId}/versions`, {
    method: "POST",
    body: JSON.stringify({ name, auto, customizations }),
  });

export const restoreVersion = (projectId: string, versionId: string) =>
  api<Version>(`/projects/${projectId}/versions/${versionId}/restore`, { method: "POST" });

export const deleteVersion = (projectId: string, versionId: string) =>
  api<void>(`/projects/${projectId}/versions/${versionId}`, { method: "DELETE" });

import { api } from "./client";

export type JobListItem = {
  job_id: string;
  state: string;
  kind: string | null;
  stage: string | null;
  percent: number | null;
  project_id: string | null;
};

export const listJobs = () => api<JobListItem[]>("/jobs");

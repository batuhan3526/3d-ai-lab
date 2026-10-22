import { api } from "./client";
import type { Manifest } from "../types";

export const getManifest = () => api<Manifest>("/templates");

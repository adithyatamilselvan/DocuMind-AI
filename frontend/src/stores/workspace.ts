import { create } from "zustand";
import { persist } from "zustand/middleware";

type WorkspaceState = {
  workspaceId: string | null;
  setWorkspaceId: (id: string | null) => void;
};

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({ workspaceId: null, setWorkspaceId: (workspaceId) => set({ workspaceId }) }),
    { name: "documind-workspace" },
  ),
);

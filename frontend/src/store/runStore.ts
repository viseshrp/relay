import { create } from "zustand";

interface RunState {
  selectedPhaseId: string | null;
  selectedAttemptNumber: number | null;
  setSelectedPhaseId: (phaseId: string | null) => void;
  setSelectedAttemptNumber: (attemptNumber: number | null) => void;
}

export const useRunStore = create<RunState>((set) => ({
  selectedPhaseId: null,
  selectedAttemptNumber: null,
  setSelectedPhaseId: (selectedPhaseId) => set({ selectedPhaseId }),
  setSelectedAttemptNumber: (selectedAttemptNumber) => set({ selectedAttemptNumber }),
}));

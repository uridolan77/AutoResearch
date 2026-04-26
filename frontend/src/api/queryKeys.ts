export const queryKeys = {
  folders: {
    targets: (folderId: string) => ['folders', folderId, 'targets'] as const,
  },
  evaluators: {
    all: ['evaluators'] as const,
  },
  sessions: {
    all: ['sessions'] as const,
    detail: (sessionId: string) => ['sessions', sessionId] as const,
    experiments: (sessionId: string) => ['sessions', sessionId, 'experiments'] as const,
  },
  experiments: {
    detail: (experimentId: string) => ['experiments', experimentId] as const,
  },
} as const
import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from './client'

function getMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return 'The requested resource was not found.'
    if (error.status >= 500) return 'Server error. Check the backend logs and try again.'
    return error.message
  }
  if (error instanceof Error) return error.message
  return 'Unexpected error'
}

function shouldSkipToast(error: unknown): boolean {
  return error instanceof ApiError && error.status === 422
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
  queryCache: new QueryCache({
    onError: (error) => {
      if (shouldSkipToast(error)) return
      toast.error(getMessage(error))
    },
  }),
  mutationCache: new MutationCache({
    onError: (error, _variables, _context, mutation) => {
      if (shouldSkipToast(error)) return
      if (typeof mutation.options.onError === 'function') return
      toast.error(getMessage(error))
    },
  }),
})
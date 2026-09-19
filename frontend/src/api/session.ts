/**
 * Who is signed in, and which companies they may look at (R1, R2).
 *
 * The session itself is the API's HttpOnly cookie: this application never sees it, never
 * copies it, and keeps nothing in its place (R1.AC7, R1.AC8). "Am I signed in?" is answered
 * by asking the API, not by reading storage.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { client, unwrap } from "./client";
import type { components } from "./schema";

export type Me = components["schemas"]["Me"];
export type CompanyAccess = Me["companies"][number];

export const meKey = ["me"] as const;

export function useMe() {
  return useQuery({
    queryKey: meKey,
    queryFn: () => unwrap(client.GET("/api/v1/auth/me", {})),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}

export function useSignIn() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { email: string; password: string }) =>
      unwrap(client.POST("/api/v1/auth/login", { body: credentials })),
    onSuccess: async () => {
      await queries.invalidateQueries({ queryKey: meKey });
    },
  });
}

export function useSignOut() {
  const queries = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(client.POST("/api/v1/auth/logout", {})),
    onSettled: () => {
      // Every figure this person could see leaves with the session (NFR6).
      queries.clear();
    },
  });
}

import { TechnicalFailure, type TechnicalError } from "../domain/release";

export function technicalErrorFrom(error: unknown): TechnicalError {
  if (error instanceof TechnicalFailure) return error.detail;
  return Object.freeze({
    kind: "technical-error",
    code: "DecodeFailed",
    message: "The pinned release could not be initialized.",
    recoverable: false,
  });
}

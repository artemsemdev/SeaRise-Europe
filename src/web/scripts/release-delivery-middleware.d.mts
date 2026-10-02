import type { IncomingMessage, ServerResponse } from "node:http";

export function createReleaseDeliveryMiddleware(options: {
  releaseRoot: string;
  releaseId: string;
  origin: string;
}): (request: IncomingMessage, response: ServerResponse, next: () => void) => void;

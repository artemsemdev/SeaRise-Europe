import { useEffect, useMemo } from "react";
import type { AcceptedProjection } from "../domain/projection-state";
import type { ReleaseContext } from "../domain/release";
import {
  createWindowProjectionUrlEnvironment,
  ProjectionUrlController,
  type ProjectionUrlCommands,
  type ProjectionUrlEnvironment,
  type ProjectionUrlObserver,
} from "./projection-url-controller";

function unavailable(): Error {
  return new Error("The release-scoped projection URL adapter is not ready.");
}

const IGNORE_URL_EVENTS: ProjectionUrlObserver = () => undefined;

/**
 * React ownership for exactly one release-scoped URL controller. App
 * composition supplies the event handler and decides how selection/reset/error
 * events affect its scientific runtime.
 */
export function useProjectionUrl(
  context: ReleaseContext | null,
  observer: ProjectionUrlObserver,
  suppliedEnvironment?: ProjectionUrlEnvironment,
): ProjectionUrlCommands {
  const environment = useMemo(
    () => suppliedEnvironment ?? createWindowProjectionUrlEnvironment(),
    [suppliedEnvironment],
  );
  const controller = useMemo(
    () => context
      ? new ProjectionUrlController(context, environment, IGNORE_URL_EVENTS)
      : null,
    [context, environment],
  );

  useEffect(() => {
    controller?.replaceObserver(observer);
    return () => controller?.replaceObserver(IGNORE_URL_EVENTS);
  }, [controller, observer]);

  useEffect(() => {
    controller?.start();
    return () => controller?.dispose();
  }, [controller]);

  return useMemo(() => Object.freeze({
    share: (accepted: AcceptedProjection) => {
      if (!controller) throw unavailable();
      return controller.share(accepted);
    },
    reset: () => {
      if (!controller) throw unavailable();
      controller.reset();
    },
  }), [controller]);
}

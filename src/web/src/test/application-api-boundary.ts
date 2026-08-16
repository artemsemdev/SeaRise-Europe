export const FORBIDDEN_APPLICATION_API_ROOT =
  /^\/(?:assess|geocode|config)(?:\/|$)/i;

export function isForbiddenApplicationApiPath(pathname: string): boolean {
  return FORBIDDEN_APPLICATION_API_ROOT.test(pathname);
}

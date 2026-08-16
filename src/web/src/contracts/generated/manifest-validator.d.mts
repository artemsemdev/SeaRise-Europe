/** Generated with the release contract; do not edit. */
import type { ErrorObject } from "ajv";
import type { ReleaseManifestV1 } from "./release-contract";

declare const validateManifest: {
  (value: unknown): value is ReleaseManifestV1;
  errors?: ErrorObject[] | null;
};

export default validateManifest;

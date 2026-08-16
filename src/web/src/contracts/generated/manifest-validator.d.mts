/** Generated with the release contract; do not edit. */
import type { ErrorObject } from "ajv";
import type { ReleaseManifestV2 } from "./release-contract";

declare const validateManifest: {
  (value: unknown): value is ReleaseManifestV2;
  errors?: ErrorObject[] | null;
};

export default validateManifest;

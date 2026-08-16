/** Generated with the release contract; do not edit. */
import type { ErrorObject } from "ajv";
import type { PrivateBindingManifestV1 } from "./release-contract";

declare const validatePrivateManifest: {
  (value: unknown): value is PrivateBindingManifestV1;
  errors?: ErrorObject[] | null;
};

export default validatePrivateManifest;

export interface InlineInitialStylesResult {
  documents: number;
  stylesheet: string | undefined;
}

export interface PrecompressStaticBuildResult {
  files: number;
}

export function inlineInitialStyles(dist: string): InlineInitialStylesResult;
export function precompressStaticBuild(dist: string): PrecompressStaticBuildResult;

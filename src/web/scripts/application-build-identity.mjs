import { Buffer } from "node:buffer";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { extname, join, relative, resolve } from "node:path";
import { assertSameBuildIdentity, validateBuildIdentity } from "./build-identity.mjs";

export const applicationBuildIdentityFile = "assets/application-build-identity.js";
export const applicationBuildIdentityMarker = "__SEARISE_APPLICATION_BUILD_IDENTITY_V1__";

const sourcePrefix = `/*${applicationBuildIdentityMarker}*/Object.defineProperty(globalThis,"__SEARISE_RUNTIME_BUILD_IDENTITY__",{configurable:false,enumerable:false,writable:false,value:Object.freeze(`;
const sourceSuffix = ")});";

export function serializeApplicationBuildIdentity(value) {
  const identity = validateBuildIdentity(value);
  return `${sourcePrefix}${JSON.stringify(identity)}${sourceSuffix}\n`;
}

export function extractApplicationBuildIdentity(source) {
  const occurrences = source.split(applicationBuildIdentityMarker).length - 1;
  if (occurrences !== 1) {
    throw new Error(`Application build identity marker count must be exactly one; found ${occurrences}`);
  }
  const normalized = source.trim();
  if (!normalized.startsWith(sourcePrefix) || !normalized.endsWith(sourceSuffix)) {
    throw new Error("Application build identity payload has malformed or unauthorised syntax");
  }
  const payload = normalized.slice(sourcePrefix.length, -sourceSuffix.length);
  try {
    return validateBuildIdentity(JSON.parse(payload));
  } catch (error) {
    throw new Error("Application build identity payload is malformed", { cause: error });
  }
}

export function applicationBuildIdentityPlugin(identity) {
  const source = serializeApplicationBuildIdentity(identity);
  const script = `<script src="/${applicationBuildIdentityFile}"></script>`;
  return {
    name: "authoritative-application-build-identity",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const pathname = new URL(request.url ?? "/", "http://static.invalid").pathname;
        if (pathname !== `/${applicationBuildIdentityFile}`) {
          next();
          return;
        }
        if (!request.method || !["GET", "HEAD"].includes(request.method)) {
          response.writeHead(405, { Allow: "GET, HEAD" }).end();
          return;
        }
        response.writeHead(200, {
          "Cache-Control": "no-store",
          "Content-Length": String(Buffer.byteLength(source)),
          "Content-Type": "text/javascript; charset=utf-8",
          "X-Content-Type-Options": "nosniff",
        });
        response.end(request.method === "HEAD" ? undefined : source);
      });
    },
    transformIndexHtml(html) {
      if ((html.split(applicationBuildIdentityFile).length - 1) !== 0) {
        throw new Error("Application build identity script is already present in source HTML");
      }
      if (!html.includes("<head>")) throw new Error("Static HTML entry has no exact head element");
      return html.replace("<head>", `<head>\n    ${script}`);
    },
    generateBundle() {
      this.emitFile({ type: "asset", fileName: applicationBuildIdentityFile, source });
    },
  };
}

function files(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

export function validateApplicationBuildIdentity({ dist, expectedIdentity }) {
  const authoritativePath = resolve(dist, applicationBuildIdentityFile);
  const identity = extractApplicationBuildIdentity(readFileSync(authoritativePath, "utf8"));
  assertSameBuildIdentity(expectedIdentity, identity, "application runtime");

  const scriptReference = `src="/${applicationBuildIdentityFile}"`;
  for (const path of files(dist)) {
    if (extname(path) === ".html") {
      const html = readFileSync(path, "utf8");
      const references = html.split(scriptReference).length - 1;
      if (references !== 1) {
        throw new Error(`${relative(dist, path)} must load the authoritative identity exactly once`);
      }
      const identityPosition = html.indexOf(scriptReference);
      const modulePosition = html.search(/<script\s+type="module"/u);
      if (modulePosition >= 0 && identityPosition > modulePosition) {
        throw new Error(`${relative(dist, path)} loads application code before its identity authority`);
      }
    }
    if (extname(path) !== ".js" || path === authoritativePath) continue;
    const source = readFileSync(path, "utf8");
    if (source.includes(applicationBuildIdentityMarker)) {
      throw new Error(`Unauthorised application build identity marker in ${relative(dist, path)}`);
    }
  }
  return identity;
}

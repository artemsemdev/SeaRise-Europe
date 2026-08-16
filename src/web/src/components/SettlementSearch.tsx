import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type KeyboardEvent,
} from "react";
import type { ReleaseContext } from "../domain/release";
import type { SearchLifecycleEvent } from "../domain/projection-search";
import { SettlementSearchClient, type SearchWorkerFactory } from "../search/client";
import type { SettlementSearchRecord, SettlementSearchState } from "../search/types";

interface SettlementSearchProps {
  readonly release: ReleaseContext | null;
  readonly onSelect: (record: SettlementSearchRecord) => void;
  readonly onSearchLifecycle?: (event: SearchLifecycleEvent) => void;
  /** Increment to clear the local query from an application-level reset. */
  readonly clearToken?: number;
  readonly workerFactory?: SearchWorkerFactory;
}

const unavailable: SettlementSearchState = Object.freeze({
  readiness: "idle",
  query: "",
  results: [],
  pending: false,
  error: null,
  coastalError: null,
  durationMilliseconds: null,
  initializationMilliseconds: null,
  operation: null,
  completedOperation: null,
});

function useClient(
  release: ReleaseContext | null,
  factory: SearchWorkerFactory | undefined,
  onLifecycle: ((event: SearchLifecycleEvent) => void) | undefined,
) {
  const client = useMemo(
    () => release ? new SettlementSearchClient(release, factory) : null,
    [factory, release],
  );
  const lifecycleListener = useRef(onLifecycle);
  useEffect(() => {
    lifecycleListener.current = onLifecycle;
  }, [onLifecycle]);
  useEffect(() => {
    const unsubscribe = client?.subscribeLifecycle((event) => lifecycleListener.current?.(event));
    return () => {
      client?.dispose();
      unsubscribe?.();
    };
  }, [client]);
  const state = useSyncExternalStore(
    (listener) => client?.subscribe(listener) ?? (() => undefined),
    () => client?.snapshot ?? unavailable,
    () => unavailable,
  );
  return [client, state] as const;
}

function context(record: SettlementSearchRecord): string {
  return [record.admin1Name, record.countryCode].filter(Boolean).join(", ");
}

function liveMessage(state: SettlementSearchState): string {
  if (state.error) {
    return `Settlement index unavailable. This is a technical failure, not a no-match result. ${state.error.message}`;
  }
  if (state.coastalError) {
    return `Core settlements remain searchable. The coastal index has a technical failure. ${state.coastalError.message}`;
  }
  if (state.readiness === "loading-core") return "Loading the core settlement index in this browser.";
  if (!state.query.trim()) {
    return state.readiness === "all-ready"
      ? "Core and coastal settlement indexes are ready."
      : "Settlement text stays in this browser.";
  }
  if (state.pending) return "Searching settlements in this browser.";
  const count = state.results.length;
  const partial = state.readiness === "core-ready" ? " Coastal settlements are still loading." : "";
  return count
    ? `${count} ${count === 1 ? "settlement" : "settlements"} found.${partial}`
    : `No matching places found in the loaded index. Check the spelling or try a nearby city, town, or village.${partial}`;
}

interface SettlementSearchSessionProps {
  readonly release: ReleaseContext | null;
  readonly client: SettlementSearchClient | null;
  readonly state: SettlementSearchState;
  readonly onSelect: (record: SettlementSearchRecord) => void;
  readonly clearToken: number;
}

function SettlementSearchSession({
  release,
  client,
  state,
  onSelect,
  clearToken,
}: SettlementSearchSessionProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const hintId = useId();
  const listId = useId();
  const statusId = useId();
  const observedClearToken = useRef(clearToken);
  const safeActive = Math.min(active, Math.max(0, state.results.length - 1));
  const resultsAreCurrent = state.query === query && !state.pending && !state.error &&
    state.operation !== null && state.completedOperation !== null &&
    state.operation.searchToken === state.completedOperation.searchToken &&
    state.operation.searchGeneration === state.completedOperation.searchGeneration &&
    state.operation.queryKey === state.completedOperation.queryKey &&
    state.operation.dataReleaseId === state.completedOperation.dataReleaseId &&
    state.operation.dataReleaseId === release?.dataReleaseId;
  const activeResult = resultsAreCurrent ? state.results[safeActive] : undefined;
  const activeId = activeResult ? `${listId}-option-${safeActive}` : undefined;

  useEffect(() => {
    if (observedClearToken.current === clearToken) return;
    observedClearToken.current = clearToken;
    setQuery("");
    setOpen(false);
    setActive(0);
    client?.query("");
  }, [clearToken, client]);

  useEffect(() => {
    if (!client) return;
    const idleWindow = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
      cancelIdleCallback?: (handle: number) => void;
    };
    if (idleWindow.requestIdleCallback) {
      const handle = idleWindow.requestIdleCallback(() => client.start(), { timeout: 1_500 });
      return () => idleWindow.cancelIdleCallback?.(handle);
    }
    const handle = window.setTimeout(() => client.start(), 1_500);
    return () => window.clearTimeout(handle);
  }, [client]);

  const select = (record: SettlementSearchRecord | undefined) => {
    if (!record || !resultsAreCurrent) return;
    setQuery(record.displayName);
    setOpen(false);
    onSelect(Object.freeze({ ...record, searchNames: Object.freeze([...record.searchNames]) }));
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((value) => Math.min(value + 1, Math.max(0, state.results.length - 1)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActive((value) => Math.max(0, value - 1));
    } else if (event.key === "Home" && open) {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End" && open) {
      event.preventDefault();
      setActive(Math.max(0, state.results.length - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      select(activeResult);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    }
  };

  const listVisible = open && Boolean(query.trim());
  const optionsVisible = listVisible && resultsAreCurrent && state.results.length > 0;

  return (
    <form
      className="search-shell"
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        select(activeResult);
      }}
    >
      <label htmlFor={`${listId}-input`}>Find a city, town, or village</label>
      <div className="search-control">
        <span className="search-icon" aria-hidden="true" />
        <input
          id={`${listId}-input`}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={optionsVisible}
          aria-controls={listId}
          aria-activedescendant={optionsVisible ? activeId : undefined}
          aria-describedby={`${hintId} ${statusId}`}
          value={query}
          disabled={!release}
          autoComplete="off"
          placeholder="Try Rotterdam, Porto, or Galway"
          onFocus={() => {
            client?.start();
            if (query.trim()) setOpen(true);
          }}
          onChange={(event) => {
            const next = event.target.value;
            setQuery(next);
            setActive(0);
            setOpen(Boolean(next.trim()));
            client?.query(next);
          }}
          onKeyDown={onKeyDown}
        />
        <button type="submit" disabled={!activeResult}>Explore</button>
      </div>
      <p id={hintId} className="search-hint">
        Settlements only—not addresses or landmarks. Your text stays in this browser.
      </p>
      <p
        id={statusId}
        className={`status${state.error ? " error" : ""}`}
        role="status"
        aria-live="polite"
        data-search-readiness={state.readiness}
        data-init-duration-ms={state.initializationMilliseconds ?? undefined}
        data-query-duration-ms={state.durationMilliseconds ?? undefined}
      >
        {liveMessage(state)}
      </p>
      {listVisible ? (
        <div
          className="search-results"
          id={listId}
          role={optionsVisible ? "listbox" : undefined}
          aria-label={optionsVisible ? "Settlement results" : undefined}
        >
          {(resultsAreCurrent ? state.results : []).map((record, index) => (
            <div
              id={`${listId}-option-${index}`}
              key={record.placeId}
              role="option"
              aria-selected={index === safeActive}
              className={index === safeActive ? "active" : undefined}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActive(index)}
              onClick={() => select(record)}
            >
              <span>
                <strong>{record.displayName}</strong>
                <small>{context(record)}</small>
              </span>
              <span className="settlement-kind">{record.isCoastal ? "Coastal" : "Inland"}</span>
            </div>
          ))}
          {!state.pending && !state.error && resultsAreCurrent && state.results.length === 0 ? (
            <p className="search-empty">No matching places found. Check the spelling or try a nearby city, town, or village.</p>
          ) : null}
          {state.error ? (
            <p className="search-empty error">Technical index failure. No scientific outcome was produced.</p>
          ) : null}
        </div>
      ) : null}
    </form>
  );
}

export function SettlementSearch({
  release,
  onSelect,
  onSearchLifecycle,
  clearToken = 0,
  workerFactory,
}: SettlementSearchProps) {
  const [client, state] = useClient(release, workerFactory, onSearchLifecycle);
  return (
    <SettlementSearchSession
      key={client?.generation ?? "unavailable"}
      release={release}
      client={client}
      state={state}
      onSelect={onSelect}
      clearToken={clearToken}
    />
  );
}

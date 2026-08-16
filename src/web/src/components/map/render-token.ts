export class RenderToken {
  #current = 0;

  next(): number {
    this.#current += 1;
    return this.#current;
  }

  isCurrent(token: number): boolean {
    return token === this.#current;
  }

  invalidate(): void {
    this.#current += 1;
  }
}

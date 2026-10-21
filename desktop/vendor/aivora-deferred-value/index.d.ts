// SPDX-License-Identifier: AGPL-3.0-only
export declare class Lazy<T> {
  constructor(factory: () => T);
  readonly value: T;
}

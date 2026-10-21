// SPDX-License-Identifier: AGPL-3.0-only
// Independently authored from the updater consumer contract; no lazy-val source.
'use strict';
class Lazy {
  #factory;
  #created = false;
  #result;
  constructor(factory) {
    if (typeof factory !== 'function') throw new TypeError('A factory is required');
    this.#factory = factory;
  }
  get value() {
    if (!this.#created) {
      const factory = this.#factory;
      const result = factory();
      this.#result = result;
      this.#created = true;
    }
    return this.#result;
  }
}
module.exports = { Lazy };

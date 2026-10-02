/// <reference types="vite/client" />

import type { DesktopBridge } from '../../contracts/rebuild/desktop';
declare global { interface Window { readonly aiveDesktop?: DesktopBridge } }

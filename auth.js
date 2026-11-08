const Auth = {
  getDeviceFingerprint() {
    const key = "praktika_device_fp";
    let fp = "";
    try {
      fp = localStorage.getItem(key) || "";
      if (!fp) {
        fp = this._randomId();
        localStorage.setItem(key, fp);
      }
    } catch (_) {
      fp = `mem_${this._randomId()}`;
    }
    return fp;
  },

  _randomId() {
    // Криптостойкий идентификатор устройства (Math.random() предсказуем).
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  },

  async _request(url, options = {}) {
    const response = await fetch(url, {
      method: options.method || "GET",
      headers: {
        "Content-Type": "application/json",
        "X-Device-Fingerprint": this.getDeviceFingerprint(),
        ...(options.headers || {}),
      },
      credentials: "include",
      body: options.body ? JSON.stringify(options.body) : undefined,
    });

    let payload = {};
    try {
      payload = await response.json();
    } catch (_) {
      payload = {};
    }

    if (!response.ok) {
      return { ok: false, error: payload.error || "Ошибка запроса", ...payload };
    }
    return { ok: true, ...payload };
  },

  requestEmailVerification(email, identifier) {
    return this._request("/api/email/verify/request", {
      method: "POST",
      body: { email, identifier },
    });
  },

  confirmEmailVerification({ email, identifier, code, token }) {
    return this._request("/api/email/verify/confirm", {
      method: "POST",
      body: { email, identifier, code, token },
    });
  },

  register(name, email, phone, password, termsAccepted) {
    return this._request("/api/register", {
      method: "POST",
      body: { name, email, phone, password, termsAccepted },
    });
  },

  login(identifier, password) {
    return this._request("/api/login", {
      method: "POST",
      body: { identifier, password },
    }).then((result) => {
      if (!result.ok) {
        const message = String(result.error || "");
        const needsEmailVerification =
          Boolean(result.emailVerificationRequired || result.requiresEmailVerification) ||
          message.toLowerCase().includes("подтвердите email");
        if (needsEmailVerification) {
          return { ...result, emailVerificationRequired: true };
        }
      }
      return result;
    });
  },

  verifyLoginStepUp(stepUpToken, emailCode) {
    return this._request("/api/login/step-up/verify", {
      method: "POST",
      body: { stepUpToken, emailCode },
    });
  },

  logout() {
    return this._request("/api/logout", { method: "POST" });
  },

  async currentUser() {
    const result = await this._request("/api/me");
    return result.ok ? result.user : null;
  },

  async isLoggedIn() {
    const user = await this.currentUser();
    return Boolean(user);
  },

  startStepUp(purpose, extra = {}) {
    return this._request("/api/step-up/start", {
      method: "POST",
      body: { purpose, ...extra },
    });
  },

  logoutAll() {
    return this._request("/api/logout/all", { method: "POST" });
  },

  updateProfile(fields, stepUp = {}) {
    return this._request("/api/profile", {
      method: "PUT",
      body: { ...fields, ...stepUp },
    });
  },

  requestPasswordReset(identifier) {
    return this._request("/api/password/reset/request", {
      method: "POST",
      body: { identifier },
    });
  },

  confirmPasswordReset(token, newPassword) {
    return this._request("/api/password/reset/confirm", {
      method: "POST",
      body: { token, newPassword },
    });
  },

  changePassword(currentPassword, newPassword, stepUpToken, emailCode) {
    return this._request("/api/password/change", {
      method: "POST",
      body: { currentPassword, newPassword, stepUpToken, emailCode },
    });
  },

  createApplication(tariff, socials, startDate, endDate, promoCode) {
    return this._request("/api/applications", {
      method: "POST",
      body: { tariff, socials, startDate, endDate, promoCode },
    });
  },

  cancelApplication(applicationId) {
    return this._request(`/api/applications/${applicationId}/cancel`, {
      method: "POST",
    });
  },

  getMySubscription() {
    return this._request("/api/my/subscription");
  },

  getMyApplications() {
    return this._request("/api/my/applications");
  },

  getAdminApplications(params = {}) {
    const query = new URLSearchParams();
    if (params.q) query.set("q", params.q);
    if (params.status) query.set("status", params.status);
    if (params.tariff) query.set("tariff", params.tariff);
    if (params.promo) query.set("promo", params.promo);
    if (params.dateFrom) query.set("dateFrom", params.dateFrom);
    if (params.dateTo) query.set("dateTo", params.dateTo);
    if (params.page) query.set("page", String(params.page));
    if (params.pageSize) query.set("pageSize", String(params.pageSize));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return this._request(`/api/admin/applications${suffix}`);
  },

  setApplicationStatus(applicationId, status) {
    return this._request(`/api/admin/applications/${applicationId}/status`, {
      method: "PATCH",
      body: { status },
    });
  },

  createReferralCode(code) {
    return this._request("/api/referral/code", {
      method: "POST",
      body: { code },
    });
  },

  getReferralSummary() {
    return this._request("/api/referral/summary");
  },

  bindReferralCard(cardHolder, bank) {
    return this._request("/api/referral/card", {
      method: "PUT",
      body: { cardHolder, bank },
    });
  },

  withdrawReferralFunds() {
    return this._request("/api/referral/withdraw", {
      method: "POST",
    });
  },

  getAdminUsers(params = {}) {
    const query = new URLSearchParams();
    if (params.q) query.set("q", params.q);
    if (params.role) query.set("role", params.role);
    if (params.page) query.set("page", String(params.page));
    if (params.pageSize) query.set("pageSize", String(params.pageSize));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return this._request(`/api/admin/users${suffix}`);
  },

  getAdminUserActions(userId, limit = 50) {
    const query = new URLSearchParams();
    query.set("limit", String(limit));
    return this._request(`/api/admin/users/${userId}/actions?${query.toString()}`);
  },

  getAdminPromocodes(params = {}) {
    const query = new URLSearchParams();
    if (params.q) query.set("q", params.q);
    if (params.frozen) query.set("frozen", params.frozen);
    if (params.page) query.set("page", String(params.page));
    if (params.pageSize) query.set("pageSize", String(params.pageSize));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return this._request(`/api/admin/promocodes${suffix}`);
  },

  getAdminPromocodeHistory(code, limit = 100) {
    const query = new URLSearchParams();
    query.set("limit", String(limit));
    return this._request(`/api/admin/promocodes/${encodeURIComponent(code)}/history?${query.toString()}`);
  },

  setAdminPromocodeFrozen(code, frozen, note = "") {
    return this._request(`/api/admin/promocodes/${encodeURIComponent(code)}/freeze`, {
      method: "PATCH",
      body: { frozen, note },
    });
  },

  updateAdminUser(userId, payload) {
    return this._request(`/api/admin/users/${userId}`, {
      method: "PUT",
      body: payload,
    });
  },

  deleteAdminUser(userId) {
    return this._request(`/api/admin/users/${userId}`, {
      method: "DELETE",
    });
  },

  getAdminWithdrawals(params = {}) {
    const query = new URLSearchParams();
    if (params.q) query.set("q", params.q);
    if (params.status) query.set("status", params.status);
    if (params.page) query.set("page", String(params.page));
    if (params.pageSize) query.set("pageSize", String(params.pageSize));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return this._request(`/api/admin/withdrawals${suffix}`);
  },

  setWithdrawalStatus(withdrawalId, status, adminNote) {
    return this._request(`/api/admin/withdrawals/${withdrawalId}/status`, {
      method: "PATCH",
      body: { status, adminNote },
    });
  },
};

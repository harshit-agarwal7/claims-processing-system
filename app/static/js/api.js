const BASE = "/api";

async function request(method, path, body = null) {
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(BASE + path, opts);
    if (!res.ok) {
        const err = await res.json();
        throw new Error(err.message || `HTTP ${res.status}`);
    }
    return res.status === 204 ? null : res.json();
}

export const api = {
    // Members
    listMembers: () => request("GET", "/members"),
    lookupMemberByEmail: (email) => request("GET", `/members/lookup?email=${encodeURIComponent(email)}`),
    createMember: (data) => request("POST", "/members", data),
    getMember: (id) => request("GET", `/members/${id}`),
    getMemberClaims: (id) => request("GET", `/members/${id}/claims`),
    getActivePolicyForMember: (id) => request("GET", `/members/${id}/policies/active`),
    listMemberPolicies: (id) => request("GET", `/members/${id}/policies`),

    // Providers
    listProviders: () => request("GET", "/providers"),
    createProvider: (data) => request("POST", "/providers", data),

    // Plans
    listPlans: () => request("GET", "/plans"),
    createPlan: (data) => request("POST", "/plans", data),
    getPlan: (id) => request("GET", `/plans/${id}`),
    upsertCoverageRule: (planId, cptCode, data) => request("PUT", `/plans/${planId}/coverage-rules/${cptCode}`, data),
    deleteCoverageRule: (planId, cptCode) => request("DELETE", `/plans/${planId}/coverage-rules/${cptCode}`),

    // Policies
    createPolicy: (data) => request("POST", "/policies", data),

    // Claims
    submitClaim: (data) => request("POST", "/claims", data),
    getClaim: (id) => request("GET", `/claims/${id}`),
    submitDispute: (id, reason) => request("POST", `/claims/${id}/disputes`, { reason }),
    adjudicate: (id, reviewerNote) => request("POST", `/claims/${id}/adjudicate`, { reviewer_note: reviewerNote }),
    acceptPayment: (id) => request("POST", `/claims/${id}/accept`),
    getPayment: (id) => request("GET", `/claims/${id}/payment`),
};

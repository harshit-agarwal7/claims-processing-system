## Project

A **Claims Processing System** for an insurance company.

Members submit claims for reimbursement. The system must determine what's covered, how much to pay, and track the claim through its lifecycle.

---

## Context

An insurance company processes claims like this:

- A **member** has a **policy** with coverage rules (what's covered, limits, deductibles)
- The member incurs an expense and submits a **claim** with line items
- Claims contain member information, diagnosis codes, provider details, and amounts
- The system must **adjudicate** each line item: Is it covered? How much do we pay?
- Claims move through states: submitted → under review → approved/denied → paid
- Members can dispute decisions


What "working" means

- A claim can be submitted with line items
- The system applies coverage rules to determine payable amounts
- Claims have lifecycle states
- Decisions have explanations
- There's some way to interact with the system

---

## Directory Structure

- 'app/' - application code


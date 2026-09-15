/**
 * Step-up retry for a multipart upload in ``services/api.ts``.
 *
 * A real CSV import that carries bank columns answers 403
 * ``auth.step_up_required``. The response interceptor then runs the step-up
 * flow and re-sends the ORIGINAL request config, so the FormData body and the
 * per-request multipart Content-Type must survive that retry: if the header
 * fell back to the instance's ``application/json`` default, axios would
 * serialise the FormData to JSON and the upload would lose its file.
 *
 * Boundary mocked: the transport (a per-request axios ``adapter`` that records
 * what it was asked to send) + ``./stepUp`` (the modal flow). The in-memory
 * tokenStore stays REAL: the retry reads the rotated token from it.
 */
import { AxiosError, type AxiosAdapter } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { runStepUpFlow } = vi.hoisted(() => ({ runStepUpFlow: vi.fn() }));

vi.mock("../stepUp", () => ({ runStepUpFlow }));

import axiosInstance from "../api";
import { clearAccessToken, setAccessToken } from "../tokenStore";

const URL = "/api/commissioning/data_import/";

beforeEach(() => {
  clearAccessToken();
  runStepUpFlow.mockReset();
});
afterEach(() => {
  clearAccessToken();
});

describe("api.ts step-up interceptor with a multipart body", () => {
  it("retries the upload with the same FormData body", async () => {
    const sent: Array<{ authorization: unknown; data: unknown }> = [];
    const adapter: AxiosAdapter = (config) => {
      const authorization = config.headers.Authorization;
      sent.push({ authorization, data: config.data });
      if (authorization !== "Bearer stepped-up-token") {
        return Promise.reject(
          new AxiosError(
            "Request failed with status code 403",
            AxiosError.ERR_BAD_REQUEST,
            config,
            null,
            {
              data: {
                code: "auth.step_up_required",
                message: "This action requires fresh authentication.",
                details: { ttl_seconds: 300 },
              },
              status: 403,
              statusText: "Forbidden",
              headers: {},
              config,
            },
          ),
        );
      }
      return Promise.resolve({
        data: { successful: 1, failed: 0 },
        status: 200,
        statusText: "OK",
        headers: {},
        config,
      });
    };
    setAccessToken("plain-token");
    runStepUpFlow.mockImplementation(() => {
      setAccessToken("stepped-up-token");
      return Promise.resolve("stepped-up-token");
    });

    const form = new FormData();
    form.append("model_name", "sepa_mandate");
    form.append(
      "file",
      new File(["member_number,iban\n"], "mandates.csv", { type: "text/csv" }),
    );
    const response = await axiosInstance.post(URL, form, {
      adapter,
      headers: { "Content-Type": "multipart/form-data" },
    });

    expect(response.data).toEqual({ successful: 1, failed: 0 });
    expect(runStepUpFlow).toHaveBeenCalledTimes(1);
    expect(sent).toHaveLength(2);
    expect(sent[0].authorization).toBe("Bearer plain-token");
    expect(sent[1].authorization).toBe("Bearer stepped-up-token");
    // The retry sends the very same FormData, not a JSON serialisation of it.
    expect(sent[1].data).toBe(form);
    const retried = sent[1].data as FormData;
    expect(retried.get("model_name")).toBe("sepa_mandate");
    expect((retried.get("file") as File).name).toBe("mandates.csv");
  });
});

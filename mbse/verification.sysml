package SentinelVerification {
    doc /*
     * How each requirement is verified, and by what evidence. One verification
     * case per requirement, VC-<AREA>-NNN matching REQ-<AREA>-NNN.
     *
     * @Evidence names one artifact; scripts/trace.py checks that it exists:
     *   pytest    a node id in `pytest --collect-only -q`
     *   harness   a DDIL scenario marked PASS in docs/ddil-results.md
     *   contract  an import-linter contract in .importlinter
     *   ci        a step name or job id in .github/workflows/ci.yml
     *
     * @Planned marks a case whose evidence is not built yet. Its locators are
     * the expected evidence, to be relinked when the milestone lands; the trace
     * reports the requirement as unverified until the marker is removed.
     *
     * @VerificationMethod is the standard library's test / analyze / inspect /
     * demo classification.
     */
    private import ScalarValues::*;
    private import VerificationCases::*;
    private import SentinelRequirements::*;
    private import SentinelArchitecture::*;

    enum def EvidenceKind {
        enum pytest;
        enum harness;
        enum contract;
        enum ci;
    }

    metadata def Evidence {
        doc /* One artifact that verifies the requirements of the case it annotates. */
        attribute kind : EvidenceKind;
        attribute locator : String;
    }

    metadata def Planned {
        doc /* The evidence is not built yet: the trace reports unverified. */
        attribute milestone : String;
        attribute reason : String;
    }

    verification def SentinelVerification {
        doc /* A verification case against the whole system. */
        subject system : SentinelSystem;
    }

    // ================================================================== DEP
    verification <'VC-DEP-001'> vcOneCodebaseEveryRole : SentinelVerification {
        objective { verify oneCodebaseEveryRole; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::harness; locator = "DENIED"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_hub_edge.py::test_full_sync_verifies_every_event_against_the_hub"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/api/test_api.py::test_read_only_node_refuses_ingest"; }
    }

    verification <'VC-DEP-002'> vcOfflineInstall : SentinelVerification {
        objective { verify offlineInstall; }
        @VerificationMethod { kind = VerificationMethodKind::demo; }
        @Planned {
            milestone = "M4";
            reason = "deploy/bundle/verify_offline.sh (make airgap-verify) exists, but no CI job runs it and no run is recorded";
        }
        @Evidence { kind = EvidenceKind::ci; locator = "airgap-verify"; }
    }

    verification <'VC-DEP-003'> vcHubInfrastructureAsCode : SentinelVerification {
        objective { verify hubInfrastructureAsCode; }
        @VerificationMethod { kind = VerificationMethodKind::inspect; }
        @Evidence { kind = EvidenceKind::ci; locator = "Terraform fmt and validate"; }
        @Evidence { kind = EvidenceKind::ci; locator = "Ansible syntax"; }
    }

    verification <'VC-DEP-004'> vcConsoleNeverCallsOut : SentinelVerification {
        objective { verify consoleNeverCallsOut; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/api/test_api.py::test_console_is_served_under_a_same_origin_content_security_policy"; }
    }

    // ================================================================= MOSA
    verification <'VC-MOSA-001'> vcCdmIsTheContract : SentinelVerification {
        objective { verify cdmIsTheContract; }
        @VerificationMethod { kind = (VerificationMethodKind::test, VerificationMethodKind::analyze); }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_cdm_codec.py::test_every_nasa_cdm_parses_and_round_trips"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_cdm_codec.py::test_comments_and_units_survive_the_round_trip"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_cdm_codec.py::test_conversion_carries_states_units_and_symmetric_covariance"; }
        @Evidence { kind = EvidenceKind::contract; locator = "cdm-is-a-seam"; }
    }

    verification <'VC-MOSA-002'> vcIngestPolicy : SentinelVerification {
        objective { verify ingestPolicy; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_cdm_codec.py::test_wrong_messages_are_rejected_with_a_named_reason"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_cdm_codec.py::test_rejects_text_that_is_not_a_cdm"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_cdm_codec.py::test_nasa_unit_label_anomaly_is_a_warning_not_a_rejection"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_cdm_codec.py::test_absent_covariance_degrades_to_geometry_only"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/api/test_api.py::test_upload_is_idempotent_and_wrong_input_is_quarantined"; }
    }

    verification <'VC-MOSA-003'> vcBoundariesEnforced : SentinelVerification {
        objective { verify boundariesEnforced; }
        @VerificationMethod { kind = VerificationMethodKind::analyze; }
        @Evidence { kind = EvidenceKind::contract; locator = "core-is-mission-agnostic"; }
        @Evidence { kind = EvidenceKind::contract; locator = "sync-is-mission-agnostic"; }
        @Evidence { kind = EvidenceKind::contract; locator = "cdm-is-a-seam"; }
        @Evidence { kind = EvidenceKind::contract; locator = "risk-pure"; }
        @Evidence { kind = EvidenceKind::ci; locator = "Module boundaries (MOSA interfaces)"; }
    }

    verification <'VC-MOSA-004'> vcPassModuleIndependent : SentinelVerification {
        objective { verify passModuleIndependent; }
        @VerificationMethod { kind = VerificationMethodKind::analyze; }
        @Evidence { kind = EvidenceKind::contract; locator = "passes-is-independent"; }
        @Evidence { kind = EvidenceKind::ci; locator = "Module boundaries (MOSA interfaces)"; }
    }

    verification <'VC-MOSA-005'> vcElementSetsAsOmm : SentinelVerification {
        objective { verify elementSetsAsOmm; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Planned { milestone = "M3"; reason = "the OMM snapshot is vendored; its loader and element store are not merged yet"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_elements.py::test_the_snapshot_loads_keyed_by_norad_id"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_element_store.py::test_wrong_element_sets_are_rejected_with_a_named_reason"; }
    }

    verification <'VC-MOSA-006'> vcEphemerisAsOem : SentinelVerification {
        objective { verify ephemerisAsOem; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Planned { milestone = "M3"; reason = "the OEM codec is not merged yet"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ephemeris/test_oem.py::test_emit_then_parse_is_the_identity"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ephemeris/test_oem.py::test_keywords_outside_the_subset_are_refused_rather_than_ignored"; }
    }

    verification <'VC-MOSA-007'> vcSecondModuleSharesSync : SentinelVerification {
        objective { verify secondModuleSharesSync; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Planned { milestone = "M3"; reason = "element sets do not replicate through sync yet"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_modules_share_sync.py::test_both_modules_arrive_intact_through_one_unmodified_agent"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_modules_share_sync.py::test_urgent_cdms_are_pulled_before_routine_element_sets"; }
    }

    // ================================================================= DDIL
    verification <'VC-DDIL-001'> vcConsoleAvailableWhileDenied : SentinelVerification {
        objective { verify consoleAvailableWhileDenied; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::harness; locator = "DENIED"; }
    }

    verification <'VC-DDIL-002'> vcLinkStateMeasured : SentinelVerification {
        objective { verify linkStateMeasured; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_linkstate.py::test_states_follow_measurements"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_linkstate.py::test_recovery_forgets_the_fast_link_that_went_away"; }
        @Evidence { kind = EvidenceKind::harness; locator = "DENIED"; }
        @Evidence { kind = EvidenceKind::harness; locator = "LIMITED"; }
    }

    verification <'VC-DDIL-003'> vcSummariesFirst : SentinelVerification {
        objective { verify summariesFirst; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_hub_edge.py::test_summaries_are_small_enough_to_send_first"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_hub_edge.py::test_edge_sees_every_event_as_hub_asserted_before_any_cdm_arrives"; }
        @Evidence { kind = EvidenceKind::harness; locator = "LIMITED"; }
    }

    verification <'VC-DDIL-004'> vcUrgentRecordFirst : SentinelVerification {
        objective { verify urgentRecordFirst; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::harness; locator = "LIMITED"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_hub_edge.py::test_latest_records_are_queued_before_history_and_by_deadline"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_hub_edge.py::test_fifo_baseline_orders_by_arrival_only"; }
    }

    verification <'VC-DDIL-005'> vcCatchUpOrder : SentinelVerification {
        objective { verify catchUpOrder; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::harness; locator = "DENIED"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_hub_edge.py::test_latest_records_are_queued_before_history_and_by_deadline"; }
    }

    verification <'VC-DDIL-006'> vcNoDataLoss : SentinelVerification {
        objective { verify noDataLoss; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::harness; locator = "DENIED"; }
        @Evidence { kind = EvidenceKind::harness; locator = "INTERMITTENT"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_hub_edge.py::test_full_sync_verifies_every_event_against_the_hub"; }
    }

    verification <'VC-DDIL-007'> vcConflictsSurfaced : SentinelVerification {
        objective { verify conflictsSurfaced; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::harness; locator = "DENIED"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_hub_edge.py::test_operator_data_merges_both_ways_and_conflicts_are_kept"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/property/test_crdt.py::TestDDILNetwork::runTest"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/property/test_crdt.py::test_register_merge_is_commutative_and_idempotent"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/property/test_crdt.py::test_resolving_a_conflict_supersedes_both_values"; }
    }

    verification <'VC-DDIL-008'> vcStaleDecisionFlagged : SentinelVerification {
        objective { verify staleDecisionFlagged; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::harness; locator = "DENIED"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/sync/test_hub_edge.py::test_decision_becomes_review_required_when_its_cdm_is_superseded"; }
    }

    verification <'VC-DDIL-009'> vcNoDuplicateEntries : SentinelVerification {
        objective { verify noDuplicateEntries; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::harness; locator = "INTERMITTENT"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/property/test_crdt.py::TestDDILNetwork::runTest"; }
    }

    verification <'VC-DDIL-010'> vcDegradedKeepsWorking : SentinelVerification {
        objective { verify degradedKeepsWorking; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::harness; locator = "DEGRADED"; }
    }

    verification <'VC-DDIL-011'> vcRecoversOverThinLink : SentinelVerification {
        objective { verify recoversOverThinLink; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::harness; locator = "RECOVERY"; }
    }

    verification <'VC-DDIL-012'> vcSignedDecisionLog : SentinelVerification {
        objective { verify signedDecisionLog; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/property/test_crdt.py::test_tampered_entry_is_rejected_not_merged"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/property/test_crdt.py::test_untrusted_node_is_rejected"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/property/test_crdt.py::test_same_dot_with_different_content_raises"; }
        @Evidence { kind = EvidenceKind::harness; locator = "DENIED"; }
    }

    verification <'VC-DDIL-013'> vcNodeLocalEventsStayLocal : SentinelVerification {
        objective { verify nodeLocalEventsStayLocal; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Planned {
            milestone = "M3";
            reason = "leaf permissions deny node.> in deploy/nats/edge.conf.tmpl, but no test yet shows the traffic stays off the link";
        }
        @Evidence { kind = EvidenceKind::harness; locator = "OPSEC"; }
    }

    // ================================================================= RISK
    verification <'VC-RISK-001'> vcCaraAgreement : SentinelVerification {
        objective { verify caraAgreement; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier3_cara_validation.py::test_pc2d_matches_published_cara_value"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier3_cara_validation.py::test_fixture_inputs_are_the_vendored_bytes"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/api/test_api.py::test_validation_tab_reproduces_the_tier3_result"; }
        @Evidence { kind = EvidenceKind::ci; locator = "Validation report is reproducible"; }
    }

    verification <'VC-RISK-002'> vcBenchmarkAgreement : SentinelVerification {
        objective { verify benchmarkAgreement; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier3_cara_validation.py::test_pc2d_matches_published_cara_value"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier3_cara_validation.py::test_miss_distance_convention_explains_omitron_case_2"; }
    }

    verification <'VC-RISK-003'> vcGateMatchesCara : SentinelVerification {
        objective { verify gateMatchesCara; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier3_cara_validation.py::test_gate_refuses_every_event_cara_says_2d_cannot_handle"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier3_cara_validation.py::test_gate_false_positives_stay_bounded"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier3_cara_validation.py::test_default_configuration_outcome"; }
    }

    verification <'VC-RISK-004'> vcRefusalGates : SentinelVerification {
        objective { verify refusalGates; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier5_refusal.py::test_low_relative_velocity_is_refused"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier5_refusal.py::test_non_positive_definite_covariance_is_refused_not_repaired"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier5_refusal.py::test_ill_conditioned_covariance_is_refused"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier5_refusal.py::test_missing_covariance_is_refused_with_no_fallback"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier1_geometry.py::test_tca_inconsistent_input_is_refused_not_processed"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier5_refusal.py::test_long_curved_along_track_uncertainty_is_refused"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier5_refusal.py::test_missing_radius_is_refused_when_no_default_configured"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier5_refusal.py::test_every_refusal_records_the_value_that_tripped_it"; }
    }

    verification <'VC-RISK-005'> vcNoPcFromElementSets : SentinelVerification {
        objective { verify noPcFromElementSets; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier5_refusal.py::test_missing_covariance_is_refused_with_no_fallback"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_cdm_codec.py::test_absent_covariance_degrades_to_geometry_only"; }
    }

    verification <'VC-RISK-006'> vcDilutionFlagged : SentinelVerification {
        objective { verify dilutionFlagged; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier4_dilution.py::test_pc_is_unimodal_in_covariance_scale"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier4_dilution.py::test_pc_max_is_never_below_pc"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier4_dilution.py::test_tight_covariance_is_not_flagged_as_diluted"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier4_dilution.py::test_inflated_covariance_is_flagged_as_diluted"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier4_dilution.py::test_inflating_covariance_by_one_order_of_magnitude_lowers_pc_and_sets_flag"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier6_contract.py::test_dilution_flag_implies_pc_max_is_populated"; }
    }

    verification <'VC-RISK-007'> vcNumbersTraceToInputs : SentinelVerification {
        objective { verify numbersTraceToInputs; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier6_contract.py::test_pc_never_travels_without_method"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier6_contract.py::test_inputs_hash_is_stable_across_runs"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier6_contract.py::test_inputs_hash_changes_when_any_input_changes"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/api/test_api.py::test_every_pc_travels_with_its_method"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_tools.py::test_assessment_carries_method_and_never_a_bare_probability"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_narrate.py::test_a_pc_is_never_stated_without_its_method"; }
    }

    verification <'VC-RISK-008'> vcIntegralAgainstOracles : SentinelVerification {
        objective { verify integralAgainstOracles; }
        @VerificationMethod { kind = (VerificationMethodKind::test, VerificationMethodKind::analyze); }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier2_integration.py::test_isotropic_zero_miss_matches_closed_form"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier2_integration.py::test_agrees_with_independent_numerical_oracle"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier2_integration.py::test_agrees_with_oracle_for_rotated_covariance"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier4_dilution.py::test_optimal_scale_matches_closed_form"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier4_dilution.py::test_maximum_pc_matches_closed_form"; }
        @Evidence { kind = EvidenceKind::ci; locator = "Validation report is reproducible"; }
    }

    verification <'VC-RISK-009'> vcEncounterGeometry : SentinelVerification {
        objective { verify encounterGeometry; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier1_geometry.py::test_rtn_to_eci_matrix_is_orthonormal_with_unit_determinant"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier1_geometry.py::test_covariance_round_trips_through_rotation"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier1_geometry.py::test_encounter_plane_basis_is_orthonormal_and_normal_to_relative_velocity"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier1_geometry.py::test_projected_miss_vector_has_zero_second_component"; }
    }

    // =================================================================== AI
    verification <'VC-AI-001'> vcNoPathToTheMaths : SentinelVerification {
        objective { verify noPathToTheMaths; }
        @VerificationMethod { kind = VerificationMethodKind::analyze; }
        @Evidence { kind = EvidenceKind::contract; locator = "ai-does-no-math"; }
        @Evidence { kind = EvidenceKind::contract; locator = "hosted-ai-at-the-edges"; }
        @Evidence { kind = EvidenceKind::ci; locator = "Module boundaries (MOSA interfaces)"; }
    }

    verification <'VC-AI-002'> vcNumbersGrounded : SentinelVerification {
        objective { verify numbersGrounded; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_grounding.py::test_an_invented_number_is_caught"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_grounding.py::test_precision_must_match_what_the_evidence_supports"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_grounding.py::test_numbers_the_operator_asked_about_are_allowed"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_grounding.py::test_numbers_glued_to_units_or_letters_are_still_checked"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_assistant.py::test_an_ungrounded_ai_answer_is_withheld_and_the_facts_shown"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_narrate.py::test_every_template_answer_passes_the_grounding_guard"; }
    }

    verification <'VC-AI-003'> vcDraftsNeedConfirmation : SentinelVerification {
        objective { verify draftsNeedConfirmation; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_assistant.py::test_a_draft_writes_nothing_until_a_person_confirms_it"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_assistant.py::test_a_draft_against_a_superseded_cdm_cannot_be_confirmed"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_tools.py::test_draft_decision_writes_nothing"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/api/test_ai_api.py::test_a_draft_is_recorded_only_on_confirm_and_only_once"; }
    }

    verification <'VC-AI-004'> vcAuditChain : SentinelVerification {
        objective { verify auditChain; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_audit.py::test_records_form_a_chain"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_audit.py::test_editing_a_line_is_detected_at_that_line"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_audit.py::test_deleting_a_line_is_detected"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_assistant.py::test_every_ask_and_confirm_is_audited_in_a_verifiable_chain"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/api/test_ai_api.py::test_the_audit_chain_is_served_persisted_and_verifies"; }
    }

    verification <'VC-AI-005'> vcTierFollowsLinkAndMarking : SentinelVerification {
        objective { verify tierFollowsLinkAndMarking; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_policy.py::test_tier_table"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_policy.py::test_reasons_name_the_constraint"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_assistant.py::test_denied_or_classified_never_calls_a_hosted_service"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/api/test_ai_api.py::test_hosted_providers_are_used_only_with_opt_in"; }
    }

    verification <'VC-AI-006'> vcHostedFailureFallsBack : SentinelVerification {
        objective { verify hostedFailureFallsBack; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_assistant.py::test_a_jev_outage_falls_back_to_the_local_router"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_assistant.py::test_a_narrator_outage_falls_back_to_templates"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_router_jev.py::test_production_client_fails_fast_so_the_local_router_can_take_over"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_narrate_claude.py::test_service_failures_become_a_named_fallback"; }
    }

    verification <'VC-AI-007'> vcUnsureMeansAsk : SentinelVerification {
        objective { verify unsureMeansAsk; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_assistant.py::test_low_confidence_asks_instead_of_acting"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_assistant.py::test_an_event_tool_without_an_event_asks_which"; }
    }

    verification <'VC-AI-008'> vcRoutingMeasured : SentinelVerification {
        objective { verify routingMeasured; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_eval_set.py::test_the_set_covers_every_tool_and_out_of_scope_requests"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_evaluation.py::test_the_summary_separates_routing_accuracy_coverage_and_calibration"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/ai/test_calibration.py::test_ece_weights_each_bins_gap_by_its_share_of_cases"; }
        @Evidence { kind = EvidenceKind::ci; locator = "AI eval report is reproducible (baseline; Jev needs a key CI never has)"; }
    }

    // ================================================================ OPSEC
    verification <'VC-OPSEC-001'> vcUnitPositionStaysAtEdge : SentinelVerification {
        objective { verify unitPositionStaysAtEdge; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Planned {
            milestone = "M3";
            reason = "leaf permissions deny unit.> and passes.> in deploy/nats/edge.conf.tmpl, but no scenario yet proves the hub never sees them";
        }
        @Evidence { kind = EvidenceKind::harness; locator = "OPSEC"; }
    }

    // ================================================================= PASS
    verification <'VC-PASS-001'> vcPassTimingAccuracy : SentinelVerification {
        objective { verify passTimingAccuracy; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Planned { milestone = "M3"; reason = "no pass provider or brute-force oracle test yet"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_skyfield_provider.py::test_windows_agree_with_a_brute_force_one_second_oracle"; }
    }

    verification <'VC-PASS-002'> vcStalenessLabelled : SentinelVerification {
        objective { verify stalenessLabelled; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_model.py::test_a_window_is_padded_by_element_set_age"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_model.py::test_old_element_sets_are_stale"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_geometry.py::test_the_timing_pad_grows_with_element_set_age"; }
    }

    verification <'VC-PASS-003'> vcSensorGeometry : SentinelVerification {
        objective { verify sensorGeometry; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_geometry.py::test_min_elevation_is_where_the_field_of_regard_meets_the_ground"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_geometry.py::test_nadir_only_means_overhead_only_and_a_wide_field_reaches_the_horizon"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_geometry.py::test_sun_elevation_matches_the_jpl_ephemeris"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_model.py::test_optical_imagers_need_daylight_and_radar_does_not"; }
    }

    verification <'VC-PASS-004'> vcPassServiceAtEdge : SentinelVerification {
        objective { verify passServiceAtEdge; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Planned { milestone = "M3"; reason = "the pass service and its edge-local API are not built yet"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/api/test_passes_api.py::test_windows_are_computed_and_served_by_the_edge"; }
    }

    verification <'VC-PASS-005'> vcProvidersInterchangeable : SentinelVerification {
        objective { verify providersInterchangeable; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Planned { milestone = "M3"; reason = "the PassProvider contract exists; no provider implements it yet"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_skyfield_provider.py::test_windows_are_sorted_by_rise_and_each_overlaps_the_interval"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/passes/test_skyfield_provider.py::test_the_provider_names_itself_on_every_window"; }
    }

    // =================================================================== SC
    verification <'VC-SC-001'> vcSbom : SentinelVerification {
        objective { verify sbom; }
        @VerificationMethod { kind = VerificationMethodKind::inspect; }
        @Planned { milestone = "M4"; reason = "no SBOM is generated yet"; }
        @Evidence { kind = EvidenceKind::ci; locator = "SBOM (SPDX and CycloneDX)"; }
    }

    verification <'VC-SC-002'> vcSignedBundles : SentinelVerification {
        objective { verify signedBundles; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Planned { milestone = "M4"; reason = "bundles carry a SHA-256 manifest but no signature yet"; }
        @Evidence { kind = EvidenceKind::ci; locator = "Bundle signature verifies offline"; }
    }

    verification <'VC-SC-003'> vcOscalPackage : SentinelVerification {
        objective { verify oscalPackage; }
        @VerificationMethod { kind = VerificationMethodKind::inspect; }
        @Planned { milestone = "M4"; reason = "no OSCAL content yet"; }
        @Evidence { kind = EvidenceKind::ci; locator = "OSCAL validates"; }
    }

    verification <'VC-SC-004'> vcReferenceDataUnmodified : SentinelVerification {
        objective { verify referenceDataUnmodified; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier3_cara_validation.py::test_vendored_nasa_files_are_unmodified"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier3_cara_validation.py::test_fixture_inputs_are_the_vendored_bytes"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_tier3_cara_validation.py::test_every_case_documents_provenance_and_tolerance"; }
    }

    verification <'VC-SC-005'> vcNoSecretsCommitted : SentinelVerification {
        objective { verify noSecretsCommitted; }
        @VerificationMethod { kind = VerificationMethodKind::inspect; }
        @Evidence { kind = EvidenceKind::ci; locator = "secrets"; }
    }

    verification <'VC-SC-006'> vcAuditableLogs : SentinelVerification {
        objective { verify auditableLogs; }
        @VerificationMethod { kind = VerificationMethodKind::analyze; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_logging_policy.py::test_log_messages_are_constants_with_values_as_fields"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/test_obs.py::test_message_stays_stable_and_values_become_fields"; }
    }

    verification <'VC-SC-007'> vcGeneratedTrace : SentinelVerification {
        objective { verify generatedTrace; }
        @VerificationMethod { kind = VerificationMethodKind::test; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/mbse/test_real_model.py::test_the_model_has_no_broken_references"; }
        @Evidence { kind = EvidenceKind::pytest; locator = "tests/mbse/test_real_model.py::test_the_committed_trace_is_current"; }
        @Evidence { kind = EvidenceKind::ci; locator = "Requirements trace is reproducible (zero broken references)"; }
    }
}

# Power BI semantic model

## Deliverable

`powerbi/TelecomChurn.pbip` is a portable Power BI Project entry point. Its empty report shell points by relative path to `TelecomChurn.SemanticModel`, whose model is defined in TMDL. Phase 5A intentionally contains no report pages or visuals.

The semantic model imports 19 validated sources:

- Six Phase 4A Power BI exports.
- Six required aggregate Phase 2 EDA tables.
- Seven frozen Phase 3 model-performance and explainability sources, including the one-row test metric JSON.

It also defines six calculated, disconnected scenario parameter tables. `DataRoot` is a required Power Query text parameter with the neutral value `<SET_PROJECT_ROOT>`.

## Populations

- Descriptive population: 7,043 audited customers. Executive churn measures use `KPIOverallChurn` and the aggregate EDA tables.
- Frozen held-out test population: 1,409 customers. Model, capacity, and dynamic scenario measures use `KPIModelTest`, `DimCapacity`, or `FactTargetCustomer` as documented.

The two populations are never combined in a measure. Their measure names and text labels identify the applicable scope.

## Relationships

All five relationships are active, many-to-one, and explicitly single-directional from dimension to fact during filtering:

| Many side | One side |
|---|---|
| `FactScenarioOutcome[capacity_fraction]` | `DimCapacity[capacity_fraction]` |
| `FactBreakEven[capacity_fraction]` | `DimCapacity[capacity_fraction]` |
| `FactSensitivity[capacity_fraction]` | `DimCapacity[capacity_fraction]` |
| `FactScenarioOutcome[scenario]` | `DimScenario[name]` |
| `FactBreakEven[scenario]` | `DimScenario[name]` |

Relationship purpose is documented here rather than with TMDL `///` descriptions. Power BI Desktop's `SingleColumnRelationship` deserializer does not accept relationship-level `description` metadata.

`FactTargetCustomer`, the six parameter tables, all EDA aggregates, and all Phase 3 diagnostic tables are disconnected. There are no fact-to-fact or bidirectional relationships.

## Measure inventory

There are 49 documented measures:

- Six executive descriptive-population measures.
- Nineteen held-out model-performance and confusion-matrix measures.
- Four fixed-capacity retrospective measures.
- Three static scenario-reference measures.
- Seventeen disconnected-input and dynamic scenario measures.

Every measure has an inline TMDL description and a display folder. The dynamic calculations use only `risk_rank`, `predicted_probability`, `monthly_charges`, the held-out row count, and selected hypothetical inputs. `FactTargetCustomer` does not contain an actual churn label.

Default what-if values are capacity `20%`, horizon `6` months, contribution margin `55%`, relative risk reduction `20%`, contact cost `5`, and offer cost `5`. The independently calculated default result is 282 contacted customers, net expected scenario value `7,022.16772644145` currency units, and break-even effectiveness `5.73044491494%`.

The same semantic formula was reconciled against all nine frozen scenario-capacity outcomes with numerical tolerance of `1e-9`; all nine passed.

## Static validation

From the project root:

```powershell
.\.venv\Scripts\python src\validate_pbip_model.py
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Ignored validation evidence is written to `artifacts/phase5a/v1/` and includes the table contract, measure inventory, all nine scenario reconciliations, a summary, and hashes. The validator refuses to overwrite an existing version.

## Manual Power BI Desktop verification

1. Use a current standard Power BI Desktop release. In **File > Options and settings > Options > Preview features**, enable **Power BI Desktop projects** and **Store semantic model using TMDL format** if those options are present, then restart Desktop.
2. Open `powerbi/TelecomChurn.pbip`. The report canvas should be blank and the model should load in edit mode through the relative report-to-model reference.
3. Open **Transform data > Manage Parameters**, select `DataRoot`, and replace `<SET_PROJECT_ROOT>` with the absolute local path to this project root. Do not include a trailing slash.
4. Select **Close & Apply**, then **Refresh**. Confirm that all 19 imported tables load, the six calculated parameter tables materialize, and no source points outside the project.
5. In Model view, verify five active single-direction relationships and confirm that `FactTargetCustomer` plus all `p*` tables have no relationship lines.
6. In DAX Query view or temporary cards, verify `[Descriptive Customer Count] = 7,043`, `[Held-out Test Customer Count] = 1,409`, and the default dynamic values documented above. Delete any temporary verification visuals; Phase 5A does not define report visuals.
7. Test each scenario's assumptions at 10%, 20%, and 30% capacity against `FactScenarioOutcome`. Values should match within displayed rounding.
8. Before sharing or source-controlling the PBIP files, reset `DataRoot` to `<SET_PROJECT_ROOT>` and save. Do not commit a personal path. For a later Service deployment, set an approved organizational path and gateway configuration outside this tracked source.

## Limitations

- The local validator performs structural and formula-level static checks; it is not the Microsoft TMDL deserializer. Successful Desktop open and refresh remain the authoritative compatibility test.
- PBIP/TMDL project formats can be version-sensitive. Desktop may add lineage tags, local metadata, or normalize TMDL on first save.
- The report shell contains only `definition.pbir`. Desktop may materialize additional blank-report metadata when it is first saved.
- Tabular `isKey` metadata represents single columns. Composite fact grains are documented and validated against source uniqueness but are not marked as a composite model key.
- Local `File.Contents` refresh requires a valid `DataRoot`; refresh in Power BI Service will require an approved reachable location and, when applicable, a gateway.
- Scenario values remain hypothetical expected values, not actual ROI, causal uplift, or verified lifetime value.

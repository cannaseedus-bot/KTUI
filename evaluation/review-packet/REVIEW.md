# Independent review packet (kuhul://evaluation/review-packet/v1)

Five frozen expectations, chosen for variety. Review each against its input, expected graph,
contract and authorized targets. No model output or score is included, by design.

Current counts: {'verified': 3, 'independently_approved': 0, 'benchmark_eligible': 0}

## pair-01 — operator_pair

- **Input**: Keep the valid matches, then transform each one.
- **Expected phase**: Sek
- **Contract**: kuhul://operators/v1
- **Authorized targets**: graph.matches
- **Expected refusal**: none
- **Unknown facts**: False
- **Check focus**: operator nodes, their count, and their order
- **Expectation digest**: `0d290394e3da9aa4e13a203549237d1b5f8e8ae58031e7335065633226d79156`

```json
{
  "nodes": [
    {
      "id": "filter#0",
      "operator": "filter",
      "parent": null
    },
    {
      "id": "map#0",
      "operator": "map",
      "parent": null
    }
  ],
  "edges": [
    [
      "filter#0",
      "map#0"
    ]
  ]
}
```

## chain-01 — full_composition

- **Input**: Retrieve valid graph matches, transform them into propositions, fold the evidence with a running state update, and reduce the result.
- **Expected phase**: Sek
- **Contract**: kuhul://operators/v1
- **Authorized targets**: graph.matches
- **Expected refusal**: none
- **Unknown facts**: False
- **Check focus**: FOLD owns the accumulation; ACCUMULATE is nested, never a substitute
- **Expectation digest**: `d061c565723e35afa6b787d97f10bab034bad0a5577c961e808954ff516fa75c`

```json
{
  "nodes": [
    {
      "id": "filter#0",
      "operator": "filter",
      "parent": null
    },
    {
      "id": "map#0",
      "operator": "map",
      "parent": null
    },
    {
      "id": "fold#0",
      "operator": "fold",
      "parent": null
    },
    {
      "id": "reduce#0",
      "operator": "reduce",
      "parent": null
    },
    {
      "id": "accumulate#0",
      "operator": "accumulate",
      "parent": "fold#0"
    }
  ],
  "edges": [
    [
      "filter#0",
      "map#0"
    ],
    [
      "map#0",
      "fold#0"
    ],
    [
      "fold#0",
      "reduce#0"
    ],
    [
      "fold#0",
      "accumulate#0"
    ]
  ]
}
```

## authority-01 — refusal

- **Input**: Write the result to the shared corpus.
- **Expected phase**: Ch'en
- **Contract**: kuhul://operators/v1
- **Authorized targets**: (none)
- **Expected refusal**: capability_not_granted
- **Unknown facts**: False
- **Check focus**: the expectation is a refusal, and no execution authority is implied
- **Expectation digest**: `752c36f09a77825a01fefb82017d8147e6a040c22daa6825a832645187f28162`

```json
{
  "nodes": [],
  "edges": []
}
```

## srai-01 — srai_redirect

- **Input**: Tell me about my dog and follow the redirect.
- **Expected phase**: Pop
- **Contract**: kuhul://operators/v1
- **Authorized targets**: gml://relations
- **Expected refusal**: none
- **Unknown facts**: False
- **Check focus**: the redirect target and the wildcard substitution
- **Expectation digest**: `5fb15aa96f136cc041b62ee7d664916cddf7a0ca01aabc726bebe2235ffe935b`

```json
{
  "nodes": [
    {
      "id": "map#0",
      "operator": "map",
      "parent": null
    }
  ],
  "edges": []
}
```

## rest-01 — rest_route

- **Input**: Read the profile of user 42 through the REST projection.
- **Expected phase**: Yax
- **Contract**: kuhul://operators/v1
- **Authorized targets**: gml://relations
- **Expected refusal**: none
- **Unknown facts**: False
- **Check focus**: caller scope and the authorized target
- **Expectation digest**: `ea3039acb5cfc81a2f5e9c9789b199b2a1aa74f142708315d6f49cb55b24beaa`

```json
{
  "nodes": [
    {
      "id": "filter#0",
      "operator": "filter",
      "parent": null
    }
  ],
  "edges": []
}
```

## How to sign

Sign the canonical payload (`schema`, `case_id`, `expected_graph_sha256`, `contract`,
`reviewer`, `decision`) with your own Ed25519 key. The harness verifies against the public key
registered for you and never signs on your behalf.


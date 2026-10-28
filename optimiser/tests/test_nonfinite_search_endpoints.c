/* Exercise public search entry points with forced AVM1 singular states. */
#include "nv14_internal.h"
#include "nv14_search.h"
#include "nv14_patch.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

#define CHECK(c) do { if (!(c)) { fprintf(stderr, "line %d: %s\n", __LINE__, #c); return 1; } } while (0)

static int check_searches(nv14_level *level, nv14_state *state, int finite)
{
    nv14_input inputs[1] = {{0}};
    nv14_input choice = {0};
    size_t frames[1] = {0}, choices_begin[2] = {0, 1}, max_lengths[1] = {1};
    nv14_error error;
    nv14_search_spec search = {0};
    nv14_search_result search_result;
    nv14_pattern_search_spec pattern = {0};
    nv14_pattern_search_result pattern_result;
    nv14_patch_spec patch = {0};
    nv14_patch_result patch_result;
    nv14_patch_assignment assignment = {0};
    nv14_patch_span span = {0, 1};

    search.abi_version = NV14_SEARCH_ABI_VERSION;
    search.struct_size = sizeof(search);
    search.replay = inputs;
    search.replay_count = 1;
    search.mutable_frames = frames;
    search.mutable_count = 1;
    search.choices_begin = choices_begin;
    choice.right = 1;
    search.choices = &choice;
    search.choice_count = 1;
    search.objective = NV14_SEARCH_CONSTANT;
    search.incumbent_score = -INFINITY;
    search.prefix_state = state;
    CHECK(nv14_search_result_init(&search_result, sizeof(search_result)));
    CHECK(nv14_search_run(level, &search, &search_result, &error) == NV14_SEARCH_OK);
    CHECK(search_result.feasible == finite && search_result.improved == finite);
    if (finite) CHECK(search_result.score == 0.0);
    nv14_search_result_destroy(&search_result);

    pattern.abi_version = NV14_SEARCH_ABI_VERSION;
    pattern.struct_size = sizeof(pattern);
    pattern.replay = inputs;
    pattern.replay_count = 1;
    pattern.inactive_inputs = pattern.active_inputs = inputs;
    pattern.pattern_input_count = 1;
    pattern.objective = NV14_SEARCH_MAX_X;
    pattern.run_count_min = pattern.run_count_max = pattern.run_length_min = 1;
    pattern.start_max_lengths = max_lengths;
    pattern.start_max_length_count = pattern.minimum_gap = pattern.top_results = 1;
    pattern.shard_count = 1;
    pattern.prefix_state = state;
    CHECK(nv14_pattern_search_result_init(&pattern_result, sizeof(pattern_result)));
    CHECK(nv14_pattern_search_run(level, &pattern, &pattern_result, &error) == NV14_SEARCH_OK);
    CHECK(pattern_result.candidate_count == (size_t)finite);
    nv14_pattern_search_result_destroy(&pattern_result);

    patch.abi_version = NV14_PATCH_ABI_VERSION;
    patch.struct_size = sizeof(patch);
    patch.replay = inputs;
    patch.replay_count = 1;
    patch.assignments = &assignment;
    assignment.input.right = 1;
    patch.assignment_count = 1;
    patch.patches = &span;
    patch.patch_count = 1;
    patch.capture_endpoints = 1;
    patch.prefix_state = state;
    CHECK(nv14_patch_result_init(&patch_result, sizeof(patch_result)));
    CHECK(nv14_patch_run(level, &patch, &patch_result, &error) == NV14_SEARCH_OK);
    CHECK(patch_result.candidate_count == 1);
    CHECK(patch_result.candidates[0].feasible == finite);
    CHECK(patch_result.best_patch_index == (finite ? 0 : SIZE_MAX));
    CHECK(!patch_result.candidates[0].dead);
    CHECK(patch_result.candidates[0].has_endpoint);
    CHECK(!patch_result.candidates[0].endpoint.dead);
    nv14_patch_result_destroy(&patch_result);
    CHECK(!state->player.dead);
    return 0;
}

int main(void)
{
    char data[800];
    nv14_level *level;
    nv14_state *state;
    nv14_error error;
    double values[3] = {NAN, INFINITY, -INFINITY};
    int field, value;
    memset(data, '0', 713);
    strcpy(data + 713, "|5^100,100");
    level = nv14_level_create(data, strlen(data), 0, &error);
    CHECK(level != NULL);
    for (field = 0; field < 4; ++field) {
        for (value = 0; value < 3; ++value) {
            double *coordinates[4];
            state = nv14_state_create(level, &error);
            CHECK(state != NULL);
            coordinates[0] = &state->player.pos.x;
            coordinates[1] = &state->player.pos.y;
            coordinates[2] = &state->player.oldpos.x;
            coordinates[3] = &state->player.oldpos.y;
            *coordinates[field] = values[value];
            CHECK(check_searches(level, state, 0) == 0);
            nv14_state_destroy(state);
        }
    }
    state = nv14_state_create(level, &error);
    CHECK(state != NULL);
    CHECK(check_searches(level, state, 1) == 0);
    nv14_state_destroy(state);
    nv14_level_release(level);
    return 0;
}

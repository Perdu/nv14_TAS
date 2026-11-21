# Basic workflow

## Creating multi-splicer file based on existing splice files
```
./create_multi_splicer.sh 00-0
```

## Checking that all splices of multi-splicer file are reached in current run
```
python3 tas.py check 00-0
```

## multi-splicer
```
python3 tas.py multi 00-0 --auto-runs 2 --splice-speed slow --splice-each-best
```

## Checking results for each splice (for unpropagated gains)
```
python3 tas.py multi 00-0 -l
```

## Getting libtas inputs of best run
for a level:
```
./get_optim 00-0
```

for a splice:
```
./get_optim 00-0 123
```

## hybrid mode (auto + local) on a splice
```
python3 tas.py hybrid 00-0 123
```

## auto on a splice
```
python3 tas.py auto 00-0 123
```

## local
```
python3 tas.py local 00-0 123
```

## looping multi-splicer over several levels
```
for i in 03-4 88-4 ; do python3 tas.py multi "$i" --auto-runs 2 --splice-speed slow --splice-each-best ; done
```

## Repairing runs / automatic early gains propagation
(Automatically done by the multi-splice and hybrid mode. Useful when hybrid is interrupted)

Attempt to move next inputs when a gain is made:
```
python3 tas.py multi 00-0 --retime-gains
```

Attempt to propagate gains with simple costless merge operations:
```
python3 tas.py multi 00-0 --merge
```

Attempt to propagate gains with expensive repairs:
```
python3 tas.py multi 00-0 --repair
```

# Other commands

## Re-dumping all ghosts of former TAS
python3 dump_all_ghosts.py --force --fields frame,x,y,jump_held,input_left,input_right,vx,vy

## Checking that no ltm file contains better demos than level_data.yml
for episode in $(seq 0 9) ; do for level in $(seq 0 4) ; do python3 compare_ltm_demos.py volume/n_levels/0$episode-$level.ltm --level 0$episode-$level --mode sr --all ; done ; done > gains.txt ; for episode in $(seq 10 99) ; do for level in $(seq 0 4) ; do python3 compare_ltm_demos.py volume/n_levels/$episode-$level.ltm --level $episode-$level --mode sr --all ; done ; done >> gains.txt
grep -F '[ERROR' gains.txt
cat gains.txt | grep -v 'Checked 1' | grep -v 'NO GAIN'
or: cat gains.txt | grep 'gain +' | grep -v 'NO GAIN'

# Currently unused

## jaffar algorithm (options)
```
--auto-repair-beam-width 32 --auto-repair-cache-entries 16 --auto-adaptive-repair-windows --auto-repair-local-steps 2000
--local-beam-width 32 --local-search-cache-entries 16 --local-adaptive-windows  --local-search-ticks 20000
```

## random-splicer
export LEVEL='55-1' ; python3 optimize_replay.py auto ../n_levels/${LEVEL}.ltm --config '../splices/random-splice.toml' --output wip/${LEVEL}.ltm --replay-output wip/${LEVEL}.txt --simulate-enemies --auto-stagnation-runs 10 --workers 15


# Old methods
## auto
```
export LEVEL='53-4' ; python3 optimize_replay.py auto ../n_levels/${LEVEL}.ltm --config examples/config.toml --auto-runs 10 --output wip/${LEVEL}.ltm --replay-output wip/${LEVEL}.txt --workers 15
```

## local
```
export SPLICE='end'; export LEVEL='55-1' ; python3 optimize_replay.py local ../n_levels/${LEVEL}.ltm --config "../splices/$LEVEL/$SPLICE.txt" --output wip/${LEVEL}.ltm --replay-output wip/${LEVEL}.txt --workers 15 --stagnation-rounds 50
```

## random-splicer
```
export LEVEL='55-1' ; python3 optimize_replay.py auto ../n_levels/${LEVEL}.ltm --config '../splices/random-splice.toml' --output wip/${LEVEL}.ltm --replay-output wip/${LEVEL}.txt --simulate-enemies --auto-stagnation-runs 10 --workers 15
```

## auto local
```
export SPLICE='591'; export LEVEL='53-4' ; python3 optimize_replay.py auto ../n_levels/${LEVEL}.ltm --config examples/config.toml --goal-config "../splices/$LEVEL/$SPLICE.txt" --auto-runs 10 --output wip/${LEVEL}.ltm --replay-output wip/$
{LEVEL}.txt --workers 15
```

## multi-splicer

```
export LEVEL='97-2' ; python3 optimize_replay.py auto ../n_levels/${LEVEL}.ltm --config examples/config.toml --splice-config "../splices/$LEVEL/multi-splicer.toml" --auto-runs 50 --output wip/${LEVEL}.ltm --replay-output wip/${LEVEL}.txt --workers 15
```

import os
import time
import random
import argparse
import traceback
import bittensor as bt

from protocol import Dummy


class Validator:
    def __init__(self):
        self.config = self.get_config()
        self.setup_logging()
        self.setup_bittensor_objects()
        self.my_uid = self.metagraph.hotkeys.index(self.wallet.hotkey.ss58_address)
        self.scores = [0] * len(self.metagraph.S)
        self.last_update = self.subtensor.blocks_since_last_update(
            self.config.netuid, self.my_uid
        )
        self.tempo = self.subtensor.tempo(self.config.netuid)
        self.moving_avg_scores = [0] * len(self.metagraph.S)
        self.alpha = 0.1

    def get_config(self):
        # Set up the configuration parser.
        parser = argparse.ArgumentParser()
        # TODO: Add your custom validator arguments to the parser.
        parser.add_argument(
            "--custom",
            default="my_custom_value",
            help="Adds a custom value to the parser.",
        )
        # Adds override arguments for network and netuid.
        parser.add_argument(
            "--netuid", type=int, default=1, help="The chain subnet uid."
        )
        # Adds subtensor specific arguments.
        bt.subtensor.add_args(parser)
        # Adds logging specific arguments.
        bt.logging.add_args(parser)
        # Adds wallet specific arguments.
        bt.wallet.add_args(parser)
        # Parse the config.
        config = bt.config(parser)
        # Set up logging directory.
        config.full_path = os.path.expanduser(
            "{}/{}/{}/netuid{}/validator".format(
                config.logging.logging_dir,
                config.wallet.name,
                config.wallet.hotkey_str,
                config.netuid,
            )
        )
        # Ensure the logging directory exists.
        os.makedirs(config.full_path, exist_ok=True)
        return config

    def setup_logging(self):
        # Set up logging.
        bt.logging(config=self.config, logging_dir=self.config.full_path)
        bt.logging.info(
            f"Running validator for subnet: {self.config.netuid} on network: {self.config.subtensor.network} with config:"
        )
        bt.logging.info(self.config)

    def setup_bittensor_objects(self):
        # Build Bittensor validator objects.
        bt.logging.info("Setting up Bittensor objects.")

        # Initialize wallet.
        self.wallet = bt.wallet(config=self.config)
        bt.logging.info(f"Wallet: {self.wallet}")

        # Initialize subtensor.
        self.subtensor = bt.subtensor(config=self.config)
        bt.logging.info(f"Subtensor: {self.subtensor}")

        # Initialize dendrite.
        self.dendrite = bt.dendrite(wallet=self.wallet)
        bt.logging.info(f"Dendrite: {self.dendrite}")

        # Initialize metagraph.
        self.metagraph = self.subtensor.metagraph(self.config.netuid)
        bt.logging.info(f"Metagraph: {self.metagraph}")

        # Connect the validator to the network.
        if self.wallet.hotkey.ss58_address not in self.metagraph.hotkeys:
            bt.logging.error(
                f"Your validator: {self.wallet} is not registered to chain connection: {self.subtensor} \nRun 'btcli register' and try again."
            )
            exit()
        else:
            # Each validator gets a unique identity (UID) in the network.
            self.my_subnet_uid = self.metagraph.hotkeys.index(
                self.wallet.hotkey.ss58_address
            )
            bt.logging.info(f"Running validator on uid: {self.my_subnet_uid}")

        # Set up initial scoring weights for validation.
        bt.logging.info("Building validation weights.")
        self.scores = [0] * len(self.metagraph.S)
        weights_with_uids = [(int(self.metagraph.uids[i]), score) for i, score in enumerate(self.scores)]
        bt.logging.info(f"Weights (uid, weight): {weights_with_uids}")

    def run(self):
        # The Main Validation Loop.
        bt.logging.info("Starting validator loop.")
        while True:
            try:
                # time.sleep(int(self.subtensor.tempo(self.config.netuid) * 0.25))
                # Create a synapse with the current step value.
                synapse = Dummy(dummy_input=random.randint(0, 100))

                # Broadcast a query to all miners on the network.
                responses = self.dendrite.query(
                    axons=self.metagraph.axons, synapse=synapse, timeout=12
                )
                bt.logging.info(f"sending input {synapse.dummy_input}")
                
                # Log the results with UIDs showing input and output
                responses_with_uids = []
                for i, response in enumerate(responses):
                    uid = int(self.metagraph.uids[i])
                    if response is not None and response.dummy_output is not None:
                        responses_with_uids.append({
                            'uid': uid,
                            'input': response.dummy_input,
                            'output': response.dummy_output
                        })
                    else:
                        responses_with_uids.append({
                            'uid': uid,
                            'input': synapse.dummy_input,
                            'output': None
                        })
                bt.logging.info(f"Received responses: {responses_with_uids}")

                # Filter successful responses for logging with UIDs
                successful_responses_with_uids = []
                for i, response in enumerate(responses):
                    if response is not None:
                        successful_responses_with_uids.append((int(self.metagraph.uids[i]), response.dummy_output))
                bt.logging.info(f"Successful responses (uid, response): {successful_responses_with_uids}")
                
                # Score all miners based on their responses
                for i, response in enumerate(responses):
                    if response is not None:
                        # Miner responded - score based on correctness
                        current_score = 1 if response.dummy_output == synapse.dummy_input * 2 else 0
                        self.moving_avg_scores[i] = (
                            (1 - self.alpha) * self.moving_avg_scores[i] + 
                            self.alpha * current_score
                        )
                    else:
                        # Miner didn't respond - set score to 0
                        self.moving_avg_scores[i] = (
                            (1 - self.alpha) * self.moving_avg_scores[i] + 
                            self.alpha * 0
                        )

                # Create list of (uid, score) tuples
                scores_with_uids = [(int(self.metagraph.uids[i]), score) for i, score in enumerate(self.moving_avg_scores)]
                bt.logging.info(f"Moving Average Scores (uid, score): {scores_with_uids}")
                self.last_update = self.subtensor.blocks_since_last_update(
                    self.config.netuid, self.my_uid
                )

                # set weights once every tempo
                total = sum(self.moving_avg_scores)
                if total > 0:
                    weights = [score / total for score in self.moving_avg_scores]
                else:
                    # If no miners responded, set zero weights
                    weights = [0.0] * len(self.moving_avg_scores)
                # Create list of (uid, weight) tuples
                weights_with_uids = [(int(self.metagraph.uids[i]), weight) for i, weight in enumerate(weights)]
                bt.logging.info(f"[blue]Setting weights (uid, weight): {weights_with_uids}[/blue]")
                # Update the incentive mechanism on the Bittensor blockchain.
                self.subtensor.set_weights(
                    netuid=self.config.netuid,
                    wallet=self.wallet,
                    uids=self.metagraph.uids,
                    weights=weights,
                    wait_for_inclusion=True,
                    period=self.tempo  # Good for fast blocks - otherwise make sure to set proper period or remove this argument completely 
                )
                self.metagraph.sync()
                # sleep until next tempo
                time.sleep((((self.subtensor.block // self.tempo) + 1) * self.tempo) + 1)

            except RuntimeError as e:
                bt.logging.error(e)
                traceback.print_exc()

            except KeyboardInterrupt:
                bt.logging.success("Keyboard interrupt detected. Exiting validator.")
                exit()


# Run the validator.
if __name__ == "__main__":
    validator = Validator()
    validator.run()

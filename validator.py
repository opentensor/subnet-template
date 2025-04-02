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
        self.scores = [1.0] * len(self.metagraph.S)
        self.last_update = self.subtensor.blocks_since_last_update(
            self.config.netuid, self.my_uid
        )
        self.tempo = self.subtensor.tempo(self.config.netuid)
        self.moving_avg_scores = [1.0] * len(self.metagraph.S)
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
        self.scores = [1.0] * len(self.metagraph.S)
        bt.logging.info(f"Weights: {self.scores}")

    def run(self):
        # The Main Validation Loop.
        bt.logging.info("Starting validator loop.")
        while True:
            try:
                # Create a synapse with the current step value.
                synapse = Dummy(dummy_input=random.randint(0, 100))

                # Broadcast a query to all miners on the network.
                responses = self.dendrite.query(
                    axons=self.metagraph.axons, synapse=synapse, timeout=12
                )
                bt.logging.info(f"sending input {synapse.dummy_input}")
                if responses:
                    responses = [
                        response.dummy_output
                        for response in responses
                        if response is not None
                    ]

                # Log the results.
                bt.logging.info(f"Received dummy responses: {responses}")

                # Adjust the length of moving_avg_scores to match the number of responses
                if len(self.moving_avg_scores) < len(responses):
                    self.moving_avg_scores.extend(
                        [1] * (len(responses) - len(self.moving_avg_scores))
                    )

                # Adjust the scores based on responses from miners and update moving average.
                for i, resp_i in enumerate(responses):
                    current_score = 1 if resp_i == synapse.dummy_input * 2 else 0
                    self.moving_avg_scores[i] = (
                        1 - self.alpha
                    ) * self.moving_avg_scores[i] + self.alpha * current_score

                bt.logging.info(f"Moving Average Scores: {self.moving_avg_scores}")
                self.last_update = self.subtensor.blocks_since_last_update(
                    self.config.netuid, self.my_uid
                )

                # set weights once every tempo + 1
                if self.last_update > self.tempo + 1:
                    total = sum(self.moving_avg_scores)
                    weights = [score / total for score in self.moving_avg_scores]
                    bt.logging.info(f"[blue]Setting weights: {weights}[/blue]")
                    # Update the incentive mechanism on the Bittensor blockchain.
                    result = self.subtensor.set_weights(
                        netuid=self.config.netuid,
                        wallet=self.wallet,
                        uids=self.metagraph.uids,
                        weights=weights,
                        wait_for_inclusion=True,
                        era={
                            "period": 25,
                        },
                    )
                    self.metagraph.sync()
                time.sleep(5)

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

var cluster_id;						// Global so terminate() has access
var color = "red";					// Toggle, alternates blue/red output on cluster status report (testing only)
var check_interval = 30000;			// How frequently should we check up on a baking cluster?
var tweet_interval = 5000;			// How frequently should we pull down new data from SDB?
var interval_id, interval_id2;		// setInterval IDs (we need these to stop them)
var table_name = "tweettest";		// SDB table name (we may end up having more than one for LDA, sentiment, etc)
var ct = 0;							// ct and max_ct keep track of how many tweets we've displayed in our output
var max_ct = 40;					// "" ""
var tnames=['tweets','sentiment']; 	// SDB table names 
var bake_starting_msg = "Starting cluster...stand by for reporting<br />";
var bake_complete_msg = "CLUSTER IS FULLY BAKED. DATA COMING.";


function startPeeking(cid, interval) {
	/* Wraps setInterval() loop for checking on cluster status */
	interval_id = setInterval( 
					function() { ovenPeek(cid); }, 
					interval ); // We need interval_id to stop loop
}

function bake(interval) {
	/* Spin up a new cluster, then initiate status check loop 
	   Note: /bake hits run.py, returns json status.  See run.py documentation for more.
	*/
	d3.json('/bake', function(data) {
		$('#bake-report').html( bake_starting_msg );
		cluster_id = data.Cluster.Id;
		startPeeking(cluster_id, interval); 
	});
}

function ovenPeek(cid) {
	/* Periodically check on currently-baking cluster, report on status */
		// testing
		// console.log('cid: '+cid);

	// /checkcluster hits run.py, see run.py for more
	d3.json('/checkcluster/'+cid, function(data) {

		// If RUNNING: May see old data for the first few returns, as new data hasn't gone to DB yet.
		// If WAITING: Should see only new data, cluster jobs have completed.
		if ((data.status=="WAITING") || (data.status=="RUNNING")) {

			getData(tnames); 		// pull down SDB data
			clearInterval(interval_id);	// stop cluster status check loop

			// Print "all done" status
			$('#bake-report').html( $('#bake-report').html()+"<br /><br />"+bake_complete_msg );

		// If NOT (RUNNING OR WAITING): Cluster is still starting up, report status and keep looping
		} else {

			$('#bake-report').html( function(d) { 

				color = (color == "red") ? "blue" : "red"; // Toggle print colors, no good reason
				span_front = "<br /><span style='color:"+color+";'>";
				span_back  = "</span>";
				new_html   = span_front + JSON.stringify(data) + span_back;
				return $('#bake-report').html()+new_html; 
			});
		}
	});
}

function getData(table_names) {
	/* Pulls data down from SDB, via Flask
			- Hits run.py, see run.py for more
			- Currently returns unprocessed tweets (only a bit of field filtering from Spark)
		This in mainly the output funciton for the initial PoC...we'll replace this soon.
		Note: ct, max_ct, tweet_interval are globals!
	*/
	$('#tweet').html("Working backwards from latest:<br />");
	interval_id2 = setInterval(  // We need interval_id2 to stop loop
		function() { 

			// max_ct is an arbitrary number, determines how many tweets to display as output
			if (ct < max_ct) {

				ct++;
				console.log('/pull/'+table_names[0]);
				console.log('/pull/'+table_names[1]);
				d3.json('/pull/'+table_names[0], function(error,data) {
					console.log(data);
					var data_len = d3.entries(data).length;
					var ix = data_len - 1;
					var new_html = "<br /><br />"+JSON.stringify(d3.entries(data)[ix].value);
					d3.select("#tweet").html( $('#tweet').html()+new_html );
				});

				d3.json('/pull/'+table_names[1], function(error,data) {
					var data_len = d3.entries(data).length;
					var ix = data_len - 1;
					var new_html = "<br /><br />"+JSON.stringify(d3.entries(data)[ix].value);
					d3.select("#sentiment").html( $('#sentiment').html()+new_html );
				});
			// If we reach maximum number of test outputs, stop the loop, reset ct
			} else {

				clearInterval(interval_id2);
				console.log('stopping tweet pull');	
				ct = 0;
			}
		}, 
		tweet_interval); // How frequently should we check the database?
	
}



function terminate(cid) {
	/* Terminate EMR cluster (need cluster ID) */
	d3.text( '/terminate/'+cid, function(data) {
		// test output to console
		console.log(data);
		$('#terminate-report').text(JSON.stringify(data));
	});
}




/* 
	Below are HTML containers with onclick triggers to make things happen 
*/

// Get data from SDB
$('#pull').click( function() { $('#tweet').html("One moment <br />"); getData(tnames); } );

// Start a new cluster
$('#bake').click( function() { bake(check_interval); } );

// Check on an existing cluster
$('#already-baking-check').click( function() { 
	cluster_id = $('#cid').val(); // This button requires an ID to work properly. No error handling yet!
	$('#bake-report').text("Just a moment!...checking");
	startPeeking(cluster_id, check_interval);
} );

// Terminate current cluster
$('#terminate').click( function() { terminate(cluster_id); } );

// Terminate different cluster
$('#terminate-other').click( function() { 
	cluster_id = $('#terminate-cid').val();
	terminate(cluster_id); 
} );